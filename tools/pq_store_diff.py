"""Power Query step differential tool (Stage D0a to D0h: slice 3 adds group by, replace, text, merge, split).

Proves on generated data that a SQL mapping of each Tier 1 Power Query step
gives the same result as the existing row-by-row step engine (transformations.py).

Cell rule (one place, `normalize_cell`): a cell is None or text. None is NOT the
same as ''. The store CSV import keeps a blank cell as '' and the step engine
returns '' for a blank CSV cell (measured: 0 None cells over 55 steps), so a SQL
mapping that returns NULL for a blank cell is a difference. From D0h on the engine itself returns
None for a COMPUTED null (a null replacement, a split part a short cell does not have, the sum of a
group of blanks); there the SQL must return NULL, and '' is a difference.

Known limit of the mutant tests: removing ORDER BY from the 5 row-slicing
operations (`mutant_no_order_by`) cannot be killed by behaviour, because DuckDB
returns insertion order for a plain scan (measured at 1,000,000 rows). That rule
is guarded by a SQL-text lint test, which is not a mutant kill.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
import tempfile
import time
from datetime import date, datetime, time as dt_time
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

from analytics_studio.file_import import MAX_CELLS, MAX_COLUMNS, ImportCandidate, parse_file
from analytics_studio.query_engine import append_candidates
from analytics_studio.store import DuckStore, import_csv_to_store
from analytics_studio.transformations import (
    _canonical_culture,
    MAX_CONDITIONAL_CLAUSES,
    MAX_DELIMITER_OCCURRENCE,
    MAX_SPLIT_POSITION,
    _CONDITIONAL_OPERATORS,
    _CONDITIONAL_VALUE_KINDS,
    TransformationError,
    apply_transformations,
    canonical_column_type,
    normalize_promoted_headers,
)


# The store's own load-order column (hidden); DuckStore.read_page orders by it, never by the physical rowid.
_RN = '"__rn"'


class Refusal:
    """Explicit refusal object representing an intentionally unsupported or invalid shape.

    `expected_error` is the engine's own error text (substring) when the engine itself rejects the
    step. A refusal without it is a named limit of the SQL mapping: the engine accepts the step.
    `rank` orders several engine errors inside one advanced filter the way the engine meets them:
    (0, clause) validation, (1, clause, sub-step) preparation, (2, row, clause) row scan.
    """

    def __init__(self, reason: str, expected_error: str | None = None, rank: tuple[int, ...] | None = None):
        self.reason = reason
        self.expected_error = expected_error
        self.rank = rank if rank is not None else (9,)

    def __repr__(self) -> str:
        return f"Refusal({self.reason!r}, expected_error={self.expected_error!r})"

    def __str__(self) -> str:
        return f"REFUSED: {self.reason}"


def refusal_matches_engine_error(refusal: Refusal, engine_err: str) -> bool:
    """Check if refusal matches expected engine error substring."""
    return bool(refusal.expected_error) and refusal.expected_error in engine_err


def normalize_cell(val: Any) -> str | None:
    """Normalize a cell for comparison: None stays None, everything else becomes text.

    None and '' are different values on both sides. The step engine never returns
    None for a CSV-parsed table and the store holds '' for a blank CSV cell.
    """
    if val is None:
        return None
    return str(val)


WHITESPACE_CELLS = [" ", "\t", "\u00a0"]

# ---------------------------------------------------------------- engine-rule mirrors

# Every character that Python's str.strip() removes (the engine strips with str.strip()).
PY_WHITESPACE = "".join(chr(c) for c in range(0x110000) if chr(c).isspace())

# The SQL decimal type for numeric compare and sort: exact, never DOUBLE.
SQL_DECIMAL = "DECIMAL(38,18)"

# SQL form accepted for a date or datetime cell (checked against the engine on the real distinct values).
STRICT_ISO_RX = (
    r"^([1-9][0-9]{3}|0[1-9][0-9]{2}|00[1-9][0-9]|000[1-9])-[0-9]{2}-[0-9]{2}"
    r"([ T][0-9]{2}:[0-9]{2}(:[0-9]{2}(\.[0-9]{1,6})?)?)?$"
)


def sql_str(value: str) -> str | Refusal:
    """The one string-literal helper: double the quote, refuse NUL and lone surrogates."""
    if "\x00" in value:
        return Refusal("A filter value with a NUL character cannot be written as a SQL literal.")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return Refusal("A filter value with a lone surrogate cannot be written as a SQL literal.")
    return "'" + value.replace("'", "''") + "'"


QUOTE_HEADER_REASON = "header name contains a double quote; not on the store path"
UNSAFE_HEADER_REASON = "header name contains a NUL or lone surrogate; not on the store path"


def unsafe_header_reason(name: str) -> str | None:
    """Why a header name cannot be pasted into a SQL identifier, or None.

    The store path quotes identifiers as "name" without escaping, so a double quote (or a
    NUL or lone surrogate) breaks the SQL. Such columns are refused by name, never escaped.
    """
    if '"' in name:
        return QUOTE_HEADER_REASON
    if "\x00" in name:
        return UNSAFE_HEADER_REASON
    try:
        name.encode("utf-8")
    except UnicodeEncodeError:
        return UNSAFE_HEADER_REASON
    return None


def engine_number(text: Any) -> Decimal | None:
    """Mirror of the engine's `_parse_number` for text: Decimal(text.strip()), finite only."""
    try:
        number = Decimal(str(text).strip())
    except (ArithmeticError, ValueError):
        return None
    return number if number.is_finite() else None


def engine_date(text: Any) -> tuple[str, datetime] | None:
    """Mirror of the engine's `_parse_row_date_or_datetime`: (kind, comparable datetime) or None.

    kind is 'naive' (a date or a datetime without offset) or 'aware' (with offset or Z).
    """
    if text is None or text == "":
        return None
    s = str(text).strip()
    if not s:
        return None
    try:
        return ("naive", datetime.combine(date.fromisoformat(s), dt_time.min))
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return ("aware" if parsed.tzinfo is not None else "naive", parsed)


def _mixed_offset_message() -> str:
    """The engine's own error text for comparing a naive with an aware datetime (taken from Python)."""
    try:
        return str(datetime(2000, 1, 1) < datetime.fromisoformat("2000-01-01T00:00:00+00:00"))
    except TypeError as exc:
        return str(exc)


def sql_num_expr(col: str) -> str:
    """Exact numeric value of a cell: strip like Python, drop digit-group underscores, cast to DECIMAL."""
    ws = sql_str(PY_WHITESPACE)
    return f"TRY_CAST(replace(trim(\"{col}\", {ws}), '_', '') AS {SQL_DECIMAL})"


def sql_dt_expr(col: str) -> str:
    """Timestamp of a cell in the strict ISO form, else NULL."""
    ws = sql_str(PY_WHITESPACE)
    inner = f"trim(\"{col}\", {ws})"
    return (
        f"CASE WHEN regexp_matches({inner}, '{STRICT_ISO_RX}') "
        f"THEN TRY_CAST(replace({inner}, 'T', ' ') AS TIMESTAMP) END"
    )


def decimal_literal(number: Decimal) -> str | None:
    """Plain digits of a Decimal if SQL_DECIMAL holds it exactly, else None."""
    if number.adjusted() >= 19 or number.adjusted() < -40:
        return None
    with localcontext() as ctx:
        ctx.prec = 100
        if number != number.quantize(Decimal(1).scaleb(-18)):
            return None
    return format(number, "f")



# D0h planted shapes for the group-by key, numeric aggregate, split, replace and text-transform columns.
# Rows 1..24 are fixed (every generated table with 24 or more rows holds them); later rows draw at random.
GRP_KEY_PLANT = [
    "g1", "G1", "g1 ", "g2", "", "g2", "g1", "1", "1.0", "g3", "G1", "g1 ",
    " ", "g2", "", "g3", "g1", "1", "g2", "G1", "1.0", "g3", "", "g1",
]
GRP_KEY_OPTIONS = ["g1", "G1", "g1 ", "g2", "g3", "", "1", "1.0", " "]
GRP_KEY2_OPTIONS = ["x", "y", "X", "", "z "]
AGG_NUM_PLANT = [
    "1", "2", " 4 ", "1_000", "-5", "-0.50", "7", "0.1", "7", "1", "007", "",
    "+3", "07", "3", "2", "-0", "0.30", "1e2", "5", "", "2", "4", "07",
]
AGG_NUM_OPTIONS = [
    "1", "2", "3", "4", " 4 ", "1_000", "-5", "-0.50", "12.5", "0.1", "0.2", "007", "7", "07", "+3",
    "-0", "1e2", ".5", "10 ", "0.30",
]
SPLIT_PLANT = [
    "a|b", "a|b|c", "|a", "a||b|", "", "a|b|c|d|e", "|", "abc", "x|", "|x|", "a.b.c", "a, b, c",
    "a::b::c", "a,b", "01|1.0", " | ", "a|b|", "||", "ab|cd", "a b|c d", "aaa", "aaaa|aa", "a|b|c", "\u00e9|\u00fc|\u00f1",
]
SPLIT_PARTS = ["a", "b", "", "cc", "ab", " ", "x.y"]
REP_PLANT = [
    "ab", "xaby", "xab", "abxab", "ababab", "aab", "AB", "Ab", "a%b", "a_b", "a\\b", "a.b",
    "it's", "aaa", "aaaa", "", "ab ab", " ab ", "abc", "bab", "x'y\"z", "100%", "[ab]", "(ab)*",
]
WORD_PLANT = [
    "hello world", "HELLO WORLD", "  lead", "tail  ", "tab\there", "\tx\t", "new\nline", "mC donald",
    "o'neil", "a1b2c3", "Title Case Words", "x\x1fy", "\x1fpad\x1f", "\x0bvt\x0b", "", "ab\x07cd",
    "x-y_z", "UPPER lower MiXeD", "123", "a  b", "d\x7fe", "tHIS iS", "end ", "\x1c\x1d\x1e x \x1e",
]


def _d0h_cells(rnd_h: random.Random, row_number: int) -> list[str]:
    """Cells of the six D0h columns for one row: planted for rows 1..24, random after."""
    k = row_number - 1
    blank = lambda: rnd_h.random() < 0.08
    if k < 24:
        # keep the random stream length the same for planted and random rows
        for _ in range(8):
            rnd_h.random()
        return [GRP_KEY_PLANT[k], GRP_KEY2_OPTIONS[k % 5], AGG_NUM_PLANT[k], SPLIT_PLANT[k], REP_PLANT[k], WORD_PLANT[k]]
    grp = "" if blank() else rnd_h.choice(GRP_KEY_OPTIONS)
    grp2 = rnd_h.choice(GRP_KEY2_OPTIONS)
    agg = "" if blank() else rnd_h.choice(AGG_NUM_OPTIONS)
    split = "" if blank() else "|".join(rnd_h.choice(SPLIT_PARTS) for _ in range(rnd_h.randint(1, 4)))
    rep = "" if blank() else rnd_h.choice(REP_PLANT)
    word = "" if blank() else rnd_h.choice(WORD_PLANT)
    return [grp, grp2, agg, split, rep, word]


def generate_pq_dataset(
    csv_file: Path,
    rows: int = 2000,
    seed: int = 42,
    include_blank_rows: bool = True,
) -> dict[str, Any]:
    """Generate a CSV dataset with mixed case, blanks, unicode, spaces, numbers, and dates.

    Planted shapes: an all-blank row every 250th row (measured: both the engine's CSV
    parser and the store import DROP all-blank rows on load, so they never reach a step), one whitespace-only entire row
    (row rows // 3, moved one down when that is a blank-row slot; spaces in every cell except num_clean, which stays blank),
    whitespace-only cells (" ", tab, NBSP U+00A0), adjacent duplicate rows and non-adjacent duplicates.
    """
    rnd = random.Random(seed)

    text_options = [
        "east", "East", "EAST", "west", "West", "west ", "west\t",
        "north", "south", "ünïcode", "ÜNÏCODE", "straße", "STRASSE",
        "with'quote", 'with"doublequote', "multi\nline",
    ]
    categories = ["A", "B", "C", "D", "E"]
    num_options = ["0", "1", "-5", "100", "200", "999999", "123.45", "-0.50"]
    date_options = ["2026-01-01", "2026-06-15", "2026-12-31", "2025-05-20"]

    # num_col is the DIRTY numeric column (a planted thousands shape "1,234.56" keeps it non-numeric);
    # num_clean is a CLEAN numeric column the engine parses everywhere (integers, decimals, negatives,
    # exponent forms, padding, digit-group underscore, a value beyond 2^53, blanks); date_col holds ISO
    # dates and dt_col ISO datetimes (space and T separators, fractions), both with blanks.
    # D0h columns (grp_key, grp_key2, agg_num, split_col, rep_col, word_col) sit before dt_col so the
    # last two columns stay dt_col and blank_col. They draw from their own generator (`rnd_h`), so the
    # random draws of every older column are unchanged.
    headers = [
        "id", "text_col", "num_col", "date_col", "cat_col", "num_clean",
        "grp_key", "grp_key2", "agg_num", "split_col", "rep_col", "word_col",
        "dt_col", "blank_col",
    ]
    n_cols = len(headers)
    rnd_h = random.Random(f"d0h-{seed}")
    clean_numeric_cols = ("num_clean", "agg_num")
    clean_options = [
        "0", "1", "10", "50", "100", "2", "9", "-5", "-0.50", "12.5", "0.1000000000000001",
        "1e3", "+7", ".5", " 5", "10 ", "1_000", "9007199254740993", "007", "-0",
    ]
    dt_options = [
        "2026-06-15 10:30:00", "2026-06-15T08:00:00", "2026-06-14 23:59:59.5", "2026-06-15 00:00:00",
        "2026-06-15 12:00", "2026-06-16 00:00:01", "2025-12-31 23:59:59", "2026-01-01T00:00:00",
    ]

    ws_row = max(3, rows // 3)
    if include_blank_rows and ws_row % 250 == 0:
        ws_row += 1

    csv_rows: list[list[str]] = []

    for i in range(1, rows + 1):
        if include_blank_rows and (i % 250 == 0):
            # Pure blank row: every cell is empty
            csv_rows.append([""] * n_cols)
            continue
        if i == ws_row:
            # Whitespace-only entire row: kept by Power Query (only null and '' are blank)
            ws_cells = [" "] * n_cols
            for numeric_name in clean_numeric_cols:
                ws_cells[headers.index(numeric_name)] = ""  # a " " cell would make a clean numeric column dirty
            csv_rows.append(ws_cells)
            continue

        dup_kind = rnd.random()
        if i <= 24:
            dup_kind = 1.0  # the planted rows 11..20 below must stay in every generated table
        if csv_rows and dup_kind < 0.05 and any(c.strip() for c in csv_rows[-1]):
            # Adjacent duplicate: identical to the previous row (never a blank or whitespace-only row)
            csv_rows.append(list(csv_rows[-1]))
            continue
        if csv_rows and 0.05 <= dup_kind < 0.08:
            # Non-adjacent duplicate: identical to a random earlier row (never a blank or whitespace-only row)
            source = csv_rows[rnd.randrange(len(csv_rows))]
            if any(c.strip() for c in source):
                csv_rows.append(list(source))
                continue

        id_str = str(i)
        t_str = rnd.choice(text_options) if rnd.random() >= 0.08 else ""
        n_str = rnd.choice(num_options) if rnd.random() >= 0.08 else ""
        d_str = rnd.choice(date_options) if rnd.random() >= 0.08 else ""
        c_str = rnd.choice(categories) if rnd.random() >= 0.08 else ""
        # case variants and trailing-space variants of the category (filter and duplicate columns)
        variant = rnd.random()
        if c_str and variant < 0.07:
            c_str = c_str.lower()
        elif c_str and variant < 0.14:
            c_str = c_str + " "
        clean_str = rnd.choice(clean_options) if rnd.random() >= 0.08 else ""
        dt_str = rnd.choice(dt_options) if rnd.random() >= 0.08 else ""
        b_str = "" if rnd.random() < 0.90 else "non_blank"

        # Plant deterministic shapes per brief D0e:
        # non-ASCII letters in text_col, numeric variations in num_col, trailing space ties in cat_col
        if i == 11:
            t_str = "café"
        elif i == 12:
            t_str = "İSTANBUL"
        elif i == 13:
            t_str = "Σ"
        elif i == 14:
            t_str = "straße"
        elif i == 15:
            n_str = "+123"
        elif i == 16:
            n_str = "1e3"
        elif i == 17:
            n_str = "-0.50"
        elif i == 18:
            n_str = "1,234.56"
        elif i == 19:
            c_str = "cat "
        elif i == 20:
            c_str = "cat"
        elif i == 21:
            # case-variant pair with row 20: a case-folding duplicate key merges them (mutant_duplicate_casefold)
            c_str = "Cat"
            clean_str = "0.1000000000000001"
        elif i in (22, 24):
            # a 16-digit integer next to a 16-decimal number: the engine's average precision rule needs more than
            # 28 digits, so the refusal does not depend on the seed (two rows each, the whitespace row hides one)
            clean_str = "9007199254740993"
        elif i == 23:
            clean_str = "0.1000000000000001"

        if rnd.random() < 0.05 and i > 21:
            t_str = rnd.choice(WHITESPACE_CELLS)
        if rnd.random() < 0.05 and i > 21:
            c_str = rnd.choice(WHITESPACE_CELLS)
        if rnd.random() < 0.03 and i > 21:
            b_str = rnd.choice(WHITESPACE_CELLS)

        if i == 1 or i == rows:
            b_str = ""

        h_cells = _d0h_cells(rnd_h, i)
        csv_rows.append([id_str, t_str, n_str, d_str, c_str, clean_str, *h_cells, dt_str, b_str])

    csv_file.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(csv_rows)

    return {"headers": headers, "rows": len(csv_rows)}


# D1a tables: their own small generated tables, so the main table (and every older step's result) is unchanged.
# Each D1a item names its table in "table" (default "main"); the table is built by `generate_d1a_csv`.
D1A_HEADERS = ["d_key", "d_text", "d_num", "d_cat", "d_delim", "d_pos", "d_paren", "d_uni", "d_clean", "d_clean2", "d_blank"]
D1A_ROWS = 40
D1A_SHAPES = ("d1a", "d1a_empty", "d1a_one_row", "d1a_one_col", "d1a_blank")


def generate_d1a_csv(csv_file: Path, seed: int, shape: str = "d1a") -> list[str]:
    """Write one D1a table and return its CSV headers.

    "d1a": a header-like first data row (promote_headers reads it: "Key", "Name", "Qty", a duplicate "Qty", a blank
    name), then D1A_ROWS rows with delimiter-bearing text (consecutive, leading, trailing and empty parts), positional
    text (unicode, an astral emoji, short cells), parenthesised text, unicode probes and planted numeric edge values
    (Arabic-Indic digit, 1e30, 1E+20, -1e25, 19 fractional digits). Its own generator (`rnd_d1a`), seeded from `seed`.
    "d1a_empty": header only. "d1a_one_row": the header-like row alone. "d1a_one_col": one text column, five rows.
    "d1a_blank": three rows of blank cells.
    """
    rnd_d1a = random.Random(f"d1a-{seed}")
    if shape == "d1a_one_col":
        headers = ["d_one"]
        body: list[list[str]] = [["a;b"], ["c"], [""], ["x;;y"], ["(z)"]]
    else:
        headers = list(D1A_HEADERS)
        first = ["Key", "Name", "Qty", "Qty", "Parts;x", "Code", "(Note)", "Name", "Score", "Score", ""]
        if shape == "d1a_blank":
            body = [[""] * len(headers) for _ in range(3)]
        elif shape == "d1a_empty":
            body = []
        elif shape == "d1a_one_row":
            body = [list(first)]
        else:
            choices = {
                1: ["red", "Red", "blue ", "", "green", "ünï", "a'b", 'x"y', "Red; blue"],
                2: ["1", "2.5", "-3", "10", "", "007", "-0.50", "100"],
                3: ["A", "B", "C", "a", "b", "", "A "],
                4: ["a;b", "a;;b", ";a", "a;", "", ";", "x;y;z", "  ;  "],
                5: ["abcdefghijkl", "hello world", "abc", "ünïcödé text", "", "0123456789ABCDEFGHIJ", "😀ab😀cd", "éé"],
                6: ["(x)", "a(b)c", "(1)(2)", "(a)(b)", "()", "", "(m)"],
                7: ["é", "ß", "٣", "😀a", "İ", "Σ", "", "ﬁ", "漢字"],
                # clean numerics: every form the engine and DECIMAL(38,18) read the same (no edge values)
                8: ["0", "1", "10", "50", "100", "2", "9", "-5", "-0.50", "12.5", "0.1000000000000001",
                    "1e3", "+7", ".5", " 5", "10 ", "1_000", "007", "-0"],
                9: ["0", "3", "20", "-7", "1.25", "", "1e2", "-0.1", "8", "1_0", "42"],
            }
            planted_num = ["٣", "1e30", "1E+20", "-1e25", "0.1234567890123456789", "1e-20", "+7", "1_000", " 5"]
            body = [list(first)]
            for n in range(1, D1A_ROWS + 1):
                row = [f"k{n:02d}"] + [rnd_d1a.choice(choices[k]) for k in range(1, 10)] + [""]
                body.append(row)
            for offset, value in enumerate(planted_num):
                body[1 + offset][2] = value  # d_num, rows k01..k09
            for offset, value in enumerate(["a;;b", ";a", "a;", "x;y;z"]):
                body[1 + offset][4] = value  # d_delim: consecutive, leading, trailing, three parts
    csv_file.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(body)
    return headers


# ---------------------------------------------------------------- D1b: its own generated table (`generate_d1b_csv`)
# Each column holds one kind of text; the convert_type items name a column. Its own random source (seeded from
# `seed`), so the main table and the D1a tables keep their draws.
D1B_HEADERS = ["b_num", "b_exp", "b_long", "b_tiny", "b_arab", "b_round", "b_bool", "b_date", "b_date_mixed", "b_dt", "b_time", "b_text", "b_grp"]
D1B_ROWS = 40
D1B_SHAPES = ("d1b", "d1b_empty", "d1b_one_row", "d1b_blank", "d1b_sparse")
D1B_CHOICES: dict[str, list[str]] = {
    "b_num": [" 12 ", "1_000", "+5", "007", "-0", "-0.0", "1.", ".5", "1.50", "2.5", "-2.5", "0.5", "1.5", "",
              "1,000", "NaN", "Infinity", "12abc", "0x1F", "-", "--1", "10 ", "1__0", "-0.50", "00.10"],
    "b_exp": ["1e3", "1E+3", "2.5e-1", "7", "", "-4E2"],
    "b_long": ["123456789012345678901234567890", "5", "", "-42", "1.25", "9999999999999999999"],
    "b_tiny": ["0.0000001", "5", "", "-0.25", "0.5", "0.000000"],
    "b_arab": ["\u0663", "5", "", "7", "12"],
    "b_round": ["2.5", "3.5", "-2.5", "-0.5", "0.5", "1.5", "-1.5", "2", "", "9223372036854775807",
                "9223372036854775808", "-9223372036854775808"],
    "b_bool": ["true", "FALSE", " True ", "yes", "1", "", "TRUE", "false "],
    "b_date": ["2024-02-29", "2024-02-30", "2023-02-28", "0001-01-01", "9999-12-31", "", "2024-13-01", "2024-02-29"],
    "b_date_mixed": ["2024-02-29", "20240229", "2024-02-29T10:00:00", "2023-01-01", ""],
    "b_dt": ["2024-02-29 10:00:00", "2024-02-29T23:59:59", "2024-02-29", "2024-02-30 10:00:00", "",
             "0001-01-01 00:00:00", "2024-02-29 25:00:00"],
    "b_time": ["10:30:15", "00:00:00", "23:59:59", "", "12:00:00", "09:05:01"],
    "b_text": ["a'b", "x", "", "Error fake", " pad ", "\u00fcn\u00ef"],
    # thousands-grouped text (en-US), drawn from its own random source so the other columns keep their draws
    "b_grp": ["1,000", "12,345.50", "-1,234,567", "1,000,000.25", "0", "", "1,00", "1.5", "+1,000", "5", "007",
              "1.", ".5", "-0", "1,0000", "12abc", "100,000", "1,234.5", "9,223,372,036,854,775,807"],
}


D1B_PLANTED = [
    ("b_num", "1_000"), ("b_exp", "1e3"), ("b_long", "123456789012345678901234567890"), ("b_tiny", "0.0000001"),
    ("b_arab", "\u0663"), ("b_date_mixed", "20240229"), ("b_dt", "2024-02-29T23:59:59"), ("b_text", "a'b"),
]


def generate_d1b_csv(csv_file: Path, seed: int, shape: str = "d1b") -> list[str]:
    """Write one D1b table and return its CSV headers.

    "d1b": D1B_ROWS rows drawn from D1B_CHOICES (padded, underscored, signed, exponent, long, tiny, Arabic-Indic,
    rounding, boolean, date, datetime and time texts, blanks, error words). "d1b_empty": header only.
    "d1b_one_row": the first drawn row. "d1b_blank": three rows of blank cells.
    """
    rnd_d1b = random.Random(f"d1b-{seed}")
    headers = list(D1B_HEADERS)
    if shape == "d1b_empty":
        body: list[list[str]] = []
    elif shape == "d1b_blank":
        body = [[""] * len(headers) for _ in range(3)]
    elif shape == "d1b_sparse":
        # sparse rows (one value or whitespace only) at the top, inside and at the bottom; full rows between them
        def one(value: str) -> list[str]:
            return [""] * (len(headers) - 1) + [value]
        full = [rnd_d1b.choice(D1B_CHOICES[h]) for h in headers]
        body = [one("x"), [" "] + [""] * (len(headers) - 1), full, one("y"),
                [rnd_d1b.choice(D1B_CHOICES[h]) for h in headers], [" ", ""] + [""] * (len(headers) - 3) + ["z"], one("w")]
    else:
        rnd_grp = random.Random(f"d1b-grp-{seed}")
        body = [[rnd_d1b.choice(D1B_CHOICES[h]) for h in headers[:-1]] + [rnd_grp.choice(D1B_CHOICES["b_grp"])]
                for _ in range(D1B_ROWS)]
        # Planted cells in rows 1 to 8 (after the draws, so the draws stay the same): each named refusal's trigger is
        # in every generated table, so the refused set of a run does not depend on the seed.
        for row_index, (column, value) in enumerate(D1B_PLANTED):
            body[row_index][headers.index(column)] = value
        if shape == "d1b_one_row":
            body = body[:1]
    csv_file.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(body)
    return headers


def build_step_catalog(headers: list[str], d1a: bool = True) -> list[dict[str, Any]]:
    """Build catalog of parameter sets for Tier 1 Power Query steps (`d1a`: the D1a items on their own tables)."""
    catalog: list[dict[str, Any]] = []
    n_cols = len(headers)

    # 1. keep_columns (parameter sets that need a 2nd or 3rd column are skipped on narrow tables)
    if n_cols >= 2:
        catalog.append({
            "id": "keep_columns_subset",
            "step": {"op": "keep_columns", "columns": [headers[0], headers[1]]},
        })
    catalog.append({
        "id": "keep_columns_single",
        "step": {"op": "keep_columns", "columns": [headers[0]]},
    })
    if n_cols >= 2:
        catalog.append({
            "id": "keep_columns_reordered_selection",
            "step": {"op": "keep_columns", "columns": [headers[2] if n_cols >= 3 else headers[1], headers[0]]},
        })
    catalog.append({
        "id": "keep_columns_all",
        "step": {"op": "keep_columns", "columns": list(headers)},
    })
    catalog.append({
        "id": "keep_columns_missing_col",
        "step": {"op": "keep_columns", "columns": [headers[0], "nonexistent_col_xyz"]},
    })

    # 2. remove_column
    remove_cols: list[str] = []
    for col in [headers[0], headers[1] if n_cols >= 2 else headers[0], headers[-1]]:
        if col not in remove_cols:
            remove_cols.append(col)
    for col in remove_cols:
        catalog.append({
            "id": f"remove_column_{col}",
            "step": {"op": "remove_column", "column": col},
        })
    catalog.append({
        "id": "remove_column_nonexistent_col",
        "step": {"op": "remove_column", "column": "nonexistent_col_xyz"},
    })
    catalog.append({
        "id": "remove_column_last_column",
        "step": {"op": "remove_column", "column": headers[0]},
        "single_column_context": True,
    })

    # 3. reorder_columns
    catalog.append({
        "id": "reorder_columns_first_only",
        "step": {"op": "reorder_columns", "columns": [headers[0]]},
    })
    if n_cols >= 2:
        catalog.append({
            "id": "reorder_columns_swap_first_two",
            "step": {"op": "reorder_columns", "columns": [headers[1], headers[0]]},
        })
        catalog.append({
            "id": "reorder_columns_reverse_all",
            "step": {"op": "reorder_columns", "columns": list(reversed(headers))},
        })
    if n_cols >= 3:
        catalog.append({
            "id": "reorder_columns_partial_middle",
            "step": {"op": "reorder_columns", "columns": [headers[2], headers[1]]},
        })
    catalog.append({
        "id": "reorder_columns_missing_col",
        "step": {"op": "reorder_columns", "columns": ["missing_xyz"]},
    })

    # 4. rename_column
    catalog.append({
        "id": "rename_column_simple",
        "step": {"op": "rename_column", "column": headers[0], "new_name": "renamed_id"},
    })
    catalog.append({
        "id": "rename_column_same_name",
        "step": {"op": "rename_column", "column": headers[0], "new_name": headers[0]},
    })
    catalog.append({
        "id": "rename_column_nonexistent_col",
        "step": {"op": "rename_column", "column": "missing_col_xyz", "new_name": "new_name"},
    })
    if n_cols >= 2:
        catalog.append({
            "id": "rename_column_existing_name",
            "step": {"op": "rename_column", "column": headers[0], "new_name": headers[1]},
        })

    # 5. duplicate_column
    catalog.append({
        "id": "duplicate_column_first",
        "step": {"op": "duplicate_column", "column": headers[0], "new_name": f"{headers[0]}_copy"},
    })
    catalog.append({
        "id": "duplicate_column_last",
        "step": {"op": "duplicate_column", "column": headers[-1], "new_name": f"{headers[-1]}_copy"},
    })
    if n_cols >= 2:
        catalog.append({
            "id": "duplicate_column_existing_name",
            "step": {"op": "duplicate_column", "column": headers[0], "new_name": headers[1]},
        })
    catalog.append({
        "id": "duplicate_column_nonexistent_col",
        "step": {"op": "duplicate_column", "column": "missing_xyz", "new_name": "dup_xyz"},
    })

    # 6. keep_top_rows
    for cnt in [0, 1, 10, 50, 100000]:
        catalog.append({
            "id": f"keep_top_rows_{cnt}",
            "step": {"op": "keep_top_rows", "count": cnt},
        })

    # 7. remove_top_rows
    for cnt in [0, 1, 10, 50, 100000]:
        catalog.append({
            "id": f"remove_top_rows_{cnt}",
            "step": {"op": "remove_top_rows", "count": cnt},
        })

    # 8. keep_bottom_rows
    for cnt in [0, 1, 10, 50, 100000]:
        catalog.append({
            "id": f"keep_bottom_rows_{cnt}",
            "step": {"op": "keep_bottom_rows", "count": cnt},
        })

    # 9. remove_bottom_rows
    for cnt in [0, 1, 10, 50, 100000]:
        catalog.append({
            "id": f"remove_bottom_rows_{cnt}",
            "step": {"op": "remove_bottom_rows", "count": cnt},
        })

    # 10. keep_range_rows
    range_params = [
        (1, 10),
        (1, 0),
        (5, 20),
        (50, 100),
        (100, 100000),
        (100000, 10),
    ]
    for first_row, count in range_params:
        catalog.append({
            "id": f"keep_range_rows_{first_row}_{count}",
            "step": {"op": "keep_range_rows", "first_row": first_row, "count": count},
        })

    # 11. remove_alternate_rows
    alt_params = [
        (1, 1, 1),
        (1, 1, 2),
        (2, 2, 3),
        (5, 1, 4),
        (1, 0, 5),
        (1, 5, 0),
        (100000, 1, 1),
    ]
    for first_row, rem, kp in alt_params:
        catalog.append({
            "id": f"remove_alternate_rows_{first_row}_{rem}_{kp}",
            "step": {
                "op": "remove_alternate_rows",
                "first_row_to_remove": first_row,
                "remove_count": rem,
                "keep_count": kp,
            },
        })

    # 12. count_rows
    catalog.append({
        "id": "count_rows",
        "step": {"op": "count_rows"},
    })

    # 13. add_index_column
    index_params = [
        ("Index", 0, 1),
        ("Index_1", 1, 1),
        ("CustomIndex", 100, 5),
        ("NegativeStart", -10, 2),
    ]
    for new_name, start, inc in index_params:
        catalog.append({
            "id": f"add_index_column_{new_name}_{start}_{inc}",
            "step": {
                "op": "add_index_column",
                "new_name": new_name,
                "start": start,
                "increment": inc,
            },
        })

    # 14. remove_blank_rows
    catalog.append({
        "id": "remove_blank_rows",
        "step": {"op": "remove_blank_rows"},
    })
    # Plain remove_blank_rows is the identity on imported CSV data (all-blank rows are dropped on
    # load). Keeping the last column(s) first makes rows blank for the step to remove.
    for tail in (1, 2):
        if n_cols >= tail:
            catalog.append({
                "id": f"remove_blank_rows_after_keep_last_{tail}",
                "pre_step": {"op": "keep_columns", "columns": list(headers[-tail:])},
                "step": {"op": "remove_blank_rows"},
            })

    # 15. append
    catalog.append({
        "id": "append_two_tables",
        "step": {"op": "append"},
        "second_table": "t_csv_2",
    })

    # Slice 2 steps:
    # 16. sort_rows
    sort_text = "cat_col" if "cat_col" in headers else headers[0]
    catalog.append({
        "id": "sort_rows_cat_asc",
        "step": {"op": "sort_rows", "column": sort_text, "direction": "asc"},
    })
    catalog.append({
        "id": "sort_rows_cat_desc",
        "step": {"op": "sort_rows", "column": sort_text, "direction": "desc"},
    })
    if "num_clean" in headers:
        for direction in ("asc", "desc"):
            catalog.append({
                "id": f"sort_rows_num_clean_{direction}",
                "step": {"op": "sort_rows", "column": "num_clean", "direction": direction},
            })
    if "num_col" in headers:
        # num_col holds a thousands shape, so the engine sorts it as text
        catalog.append({
            "id": "sort_rows_num_col_asc",
            "step": {"op": "sort_rows", "column": "num_col", "direction": "asc"},
        })
    if "text_col" in headers:
        # the engine sorts text in raw code point order (case_sensitive=True); the SQL matches it
        catalog.append({
            "id": "sort_rows_text_col_non_ascii",
            "step": {"op": "sort_rows", "column": "text_col", "direction": "asc"},
        })
    for col in ("date_col", "dt_col"):
        if col in headers:
            catalog.append({
                "id": f"sort_rows_{col}_desc",
                "step": {"op": "sort_rows", "column": col, "direction": "desc"},
            })
    catalog.append({
        "id": "sort_rows_missing_col",
        "step": {"op": "sort_rows", "column": "missing_xyz", "direction": "asc"},
    })

    # 17. sort_rows_by_columns
    if n_cols >= 2:
        c1 = "cat_col" if "cat_col" in headers else headers[0]
        c2 = headers[1] if headers[1] != c1 and headers[1] != "text_col" else headers[0]
        catalog.append({
            "id": "sort_rows_by_columns_two_cols",
            "step": {"op": "sort_rows_by_columns", "sorts": [{"column": c1, "direction": "asc"}, {"column": c2, "direction": "desc"}]},
        })
    if "num_clean" in headers and "cat_col" in headers:
        catalog.append({
            "id": "sort_rows_by_columns_num_clean_then_cat",
            "step": {"op": "sort_rows_by_columns", "sorts": [
                {"column": "num_clean", "direction": "desc"}, {"column": "cat_col", "direction": "asc"},
            ]},
        })
    catalog.append({
        "id": "sort_rows_by_columns_missing_col",
        "step": {"op": "sort_rows_by_columns", "sorts": [{"column": "missing_xyz", "direction": "asc"}]},
    })

    # 18. filter_rows
    target_text_col = "cat_col" if "cat_col" in headers else headers[0]

    def _filter_item(item_id: str, column: str, operator: str, value: str) -> None:
        catalog.append({
            "id": item_id,
            "step": {"op": "filter_rows", "column": column, "operator": operator, "value": value},
        })

    _filter_item("filter_rows_equals", target_text_col, "equals", "A")
    _filter_item("filter_rows_not_equals", target_text_col, "not_equals", "A")
    _filter_item("filter_rows_is_null", target_text_col, "is_null", "")
    _filter_item("filter_rows_is_not_null", target_text_col, "is_not_null", "")
    _filter_item("filter_rows_is_blank", target_text_col, "is_blank", "")
    _filter_item("filter_rows_is_not_blank", target_text_col, "is_not_blank", "")
    _filter_item("filter_rows_contains", target_text_col, "contains", "B")
    _filter_item("filter_rows_does_not_contain", target_text_col, "does_not_contain", "B")
    _filter_item("filter_rows_begins_with", target_text_col, "begins_with", "A")
    _filter_item("filter_rows_does_not_begin_with", target_text_col, "does_not_begin_with", "A")
    _filter_item("filter_rows_ends_with", target_text_col, "ends_with", "C")
    _filter_item("filter_rows_does_not_end_with", target_text_col, "does_not_end_with", "C")
    # trailing-space and case-variant equality, quotes in the value
    _filter_item("filter_rows_equals_trailing_space_cat", target_text_col, "equals", "cat")
    _filter_item("filter_rows_equals_trailing_space_variant", target_text_col, "equals", "A ")
    _filter_item("filter_rows_equals_lower_variant", target_text_col, "equals", "a")
    _filter_item("filter_rows_not_equals_lower_variant", target_text_col, "not_equals", "a")
    _filter_item("filter_rows_ends_with_space", target_text_col, "ends_with", " ")
    if "text_col" in headers:
        _filter_item("filter_rows_equals_quote", "text_col", "equals", "with'quote")
        _filter_item("filter_rows_contains_quote", "text_col", "contains", "'")
    # a comparison value on an operator that takes none: the engine rejects the step
    blank_value_target = "date_col" if "date_col" in headers else target_text_col
    for operator in ("is_blank", "is_not_blank", "is_null", "is_not_null", "is_earliest", "is_latest"):
        _filter_item(f"filter_rows_{operator}_with_value", blank_value_target, operator, "x")
    for col, tag in (("date_col", "date"), ("dt_col", "dt")):
        if col not in headers:
            continue
        for operator in ("date_before", "date_after", "date_on_or_before", "date_on_or_after"):
            _filter_item(f"filter_rows_{operator}" if tag == "date" else f"filter_rows_dt_{operator}", col, operator, "2026-06-15")
        _filter_item(f"filter_rows_{tag}_is_earliest", col, "is_earliest", "")
        _filter_item(f"filter_rows_{tag}_is_latest", col, "is_latest", "")
    if "dt_col" in headers:
        for operator in ("date_before", "date_after", "date_on_or_before", "date_on_or_after"):
            _filter_item(f"filter_rows_dt_time_{operator}", "dt_col", operator, "2026-06-15 10:30:00")
    if "date_col" in headers:
        _filter_item("filter_rows_date_value_with_time", "date_col", "date_after", "2026-06-15 12:00:00")
        _filter_item("filter_rows_date_value_invalid", "date_col", "date_before", "not a date")
    numeric_target = "num_clean" if "num_clean" in headers else ("num_col" if "num_col" in headers else None)
    if numeric_target is not None:
        _filter_item("filter_rows_numeric_greater_than", numeric_target, "greater_than", "10")
        _filter_item("filter_rows_numeric_less_than", numeric_target, "less_than", "100")
        _filter_item("filter_rows_numeric_greater_than_or_equal", numeric_target, "greater_than_or_equal", "0")
        _filter_item("filter_rows_numeric_less_than_or_equal", numeric_target, "less_than_or_equal", "50")
        _filter_item("filter_rows_numeric_column_equals_text", numeric_target, "equals", "5")
        _filter_item("filter_rows_numeric_greater_than_exponent_value", numeric_target, "greater_than", "1e1")
        _filter_item("filter_rows_numeric_greater_than_big", numeric_target, "greater_than", "9007199254740992")
        _filter_item("filter_rows_numeric_value_not_a_number", numeric_target, "greater_than", "abc")
        _filter_item("filter_rows_numeric_value_blank", numeric_target, "less_than", "")
    if "num_col" in headers and numeric_target != "num_col":
        # the dirty column: the engine stops at its first non-numeric cell
        _filter_item("filter_rows_numeric_dirty_greater_than", "num_col", "greater_than", "10")
        _filter_item("filter_rows_numeric_dirty_less_than_or_equal", "num_col", "less_than_or_equal", "50")
    catalog.append({
        "id": "filter_rows_missing_col",
        "step": {"op": "filter_rows", "column": "missing_xyz", "operator": "equals", "value": "test"},
    })

    # 19. filter_rows_advanced
    clauses = [
        {"column": target_text_col, "operator": "equals", "value": "A", "join": "and"},
    ]
    if "date_col" in headers:
        clauses.append({"column": "date_col", "operator": "date_before", "value": "2026-06-15", "join": "and"})
    clauses.append({"column": target_text_col, "operator": "equals", "value": "B", "join": "or"})
    catalog.append({
        "id": "filter_rows_advanced_combo",
        "step": {"op": "filter_rows_advanced", "clauses": clauses},
    })
    if "num_clean" in headers and "dt_col" in headers:
        catalog.append({
            "id": "filter_rows_advanced_numeric_and_datetime",
            "step": {"op": "filter_rows_advanced", "clauses": [
                {"column": "num_clean", "operator": "greater_than_or_equal", "value": "10", "join": "and"},
                {"column": "dt_col", "operator": "date_before", "value": "2026-06-15 12:00:00", "join": "and"},
                {"column": target_text_col, "operator": "equals", "value": "cat ", "join": "or"},
            ]},
        })
    if "num_col" in headers and "num_clean" in headers:
        catalog.append({
            "id": "filter_rows_advanced_dirty_numeric_clause",
            "step": {"op": "filter_rows_advanced", "clauses": [
                {"column": target_text_col, "operator": "equals", "value": "A", "join": "and"},
                {"column": "num_col", "operator": "less_than", "value": "5", "join": "and"},
            ]},
        })
        catalog.append({
            "id": "filter_rows_advanced_numeric_value_not_a_number",
            "step": {"op": "filter_rows_advanced", "clauses": [
                {"column": "num_clean", "operator": "greater_than", "value": "1_0x", "join": "and"},
            ]},
        })
    if "dt_col" in headers:
        catalog.append({
            "id": "filter_rows_advanced_blank_operator_with_value",
            "step": {"op": "filter_rows_advanced", "clauses": [
                {"column": "dt_col", "operator": "is_blank", "value": "x", "join": "and"},
            ]},
        })
    catalog.append({
        "id": "filter_rows_advanced_missing_col",
        "step": {"op": "filter_rows_advanced", "clauses": [{"column": "missing_xyz", "operator": "equals", "value": "val", "join": "and"}]},
    })

    # 20. remove_duplicates
    catalog.append({
        "id": "remove_duplicates_single_col",
        "step": {"op": "remove_duplicates", "columns": [target_text_col]},
    })
    if n_cols >= 2:
        c_sec = headers[1] if headers[0] == target_text_col else headers[0]
        catalog.append({
            "id": "remove_duplicates_two_cols",
            "step": {"op": "remove_duplicates", "columns": [target_text_col, c_sec]},
        })
    catalog.append({
        "id": "remove_duplicates_missing_col",
        "step": {"op": "remove_duplicates", "columns": ["missing_xyz"]},
    })

    # 21. keep_duplicates
    catalog.append({
        "id": "keep_duplicates_single_col",
        "step": {"op": "keep_duplicates", "columns": [target_text_col]},
    })
    if n_cols >= 2:
        c_sec = headers[1] if headers[0] == target_text_col else headers[0]
        catalog.append({
            "id": "keep_duplicates_two_cols",
            "step": {"op": "keep_duplicates", "columns": [target_text_col, c_sec]},
        })
    catalog.append({
        "id": "keep_duplicates_missing_col",
        "step": {"op": "keep_duplicates", "columns": ["missing_xyz"]},
    })

    # 22. fill_down & fill_up
    catalog.append({
        "id": "fill_down_single_col",
        "step": {"op": "fill_down", "columns": [target_text_col]},
    })
    if n_cols >= 2:
        c_sec = headers[1] if headers[0] == target_text_col else headers[0]
        catalog.append({
            "id": "fill_down_two_cols",
            "step": {"op": "fill_down", "columns": [target_text_col, c_sec]},
        })
    catalog.append({
        "id": "fill_down_missing_col",
        "step": {"op": "fill_down", "columns": ["missing_xyz"]},
    })
    catalog.append({
        "id": "fill_up_single_col",
        "step": {"op": "fill_up", "columns": [target_text_col]},
    })
    if n_cols >= 2:
        c_sec = headers[1] if headers[0] == target_text_col else headers[0]
        catalog.append({
            "id": "fill_up_two_cols",
            "step": {"op": "fill_up", "columns": [target_text_col, c_sec]},
        })
    catalog.append({
        "id": "fill_up_missing_col",
        "step": {"op": "fill_up", "columns": ["missing_xyz"]},
    })

    catalog.extend(_d0h_catalog(headers))
    if d1a:
        catalog.extend(_d1a_catalog())
        catalog.extend(_d1b_catalog())

    return catalog


def _d0h_catalog(headers: list[str]) -> list[dict[str, Any]]:
    """D0h step items: group by, replace, text transforms, merge, split. Each needs its columns in `headers`."""
    h = set(headers)
    items: list[dict[str, Any]] = []

    def add(item_id: str, step: dict[str, Any]) -> None:
        items.append({"id": item_id, "step": step})

    # --- group by
    if {"grp_key", "grp_key2", "agg_num", "cat_col", "word_col"} <= h:
        def agg(op: str, column: str | None, name: str) -> dict[str, str]:
            return {"operation": op, "new_name": name, **({"column": column} if column else {})}

        key = ["grp_key"]
        add("group_by_count_rows", {"op": "group_by", "columns": key, "aggregations": [agg("count_rows", None, "n")]})
        add("group_by_count_distinct_rows", {"op": "group_by", "columns": key, "aggregations": [agg("count_distinct_rows", None, "n")]})
        add("group_by_count_distinct_values", {"op": "group_by", "columns": key, "aggregations": [agg("count_distinct_values", "cat_col", "n")]})
        for op in ("average",):
            add(f"group_by_{op}_agg_num", {"op": "group_by", "columns": key, "aggregations": [agg(op, "agg_num", "v")]})
        add("group_by_all_aggregates", {"op": "group_by", "columns": key, "aggregations": [
            agg("count_rows", None, "rows"), agg("count_distinct_rows", None, "distinct_rows"),
            agg("count_distinct_values", "cat_col", "cats"), agg("sum", "agg_num", "total"),
            agg("average", "agg_num", "mean"), agg("median", "agg_num", "mid"),
            agg("min", "agg_num", "lo"), agg("max", "agg_num", "hi"),
            agg("min", "word_col", "lo_text"), agg("max", "word_col", "hi_text"),
        ]})
        add("group_by_two_keys", {"op": "group_by", "columns": ["grp_key", "grp_key2"], "aggregations": [
            agg("count_rows", None, "n"), agg("sum", "agg_num", "total")]})
        add("group_by_key_blank_col", {"op": "group_by", "columns": ["blank_col"], "aggregations": [
            agg("count_rows", None, "n"), agg("min", "grp_key2", "lo")]})
        add("group_by_sum_missing_key", {"op": "group_by", "columns": ["missing_xyz"], "aggregations": [agg("count_rows", None, "n")]})
        add("group_by_sum_missing_agg_column", {"op": "group_by", "columns": key, "aggregations": [agg("sum", "missing_xyz", "v")]})
        add("group_by_duplicate_key", {"op": "group_by", "columns": ["grp_key", "grp_key"], "aggregations": [agg("count_rows", None, "n")]})
        add("group_by_output_name_conflict", {"op": "group_by", "columns": key, "aggregations": [agg("count_rows", None, "grp_key")]})
        if "num_col" in h:
            add("group_by_sum_dirty_num_col", {"op": "group_by", "columns": key, "aggregations": [agg("sum", "num_col", "v")]})
            add("group_by_min_dirty_num_col", {"op": "group_by", "columns": key, "aggregations": [agg("min", "num_col", "v")]})
        if "num_clean" in h:
            add("group_by_sum_num_clean", {"op": "group_by", "columns": key, "aggregations": [agg("sum", "num_clean", "v")]})
            add("group_by_average_num_clean", {"op": "group_by", "columns": key, "aggregations": [agg("average", "num_clean", "v")]})
        if "text_col" in h:
            add("group_by_sum_text_col", {"op": "group_by", "columns": key, "aggregations": [agg("sum", "text_col", "v")]})
            add("group_by_min_text_col", {"op": "group_by", "columns": key, "aggregations": [agg("min", "text_col", "v")]})
            add("group_by_key_text_col", {"op": "group_by", "columns": ["text_col"], "aggregations": [agg("count_rows", None, "n")]})

    # --- replace_value and replace_error_values
    if "rep_col" in h:
        def rep(item_id: str, value: Any, replacement: Any, replacer: str | None = None, column: str = "rep_col") -> None:
            step = {"op": "replace_value", "column": column, "value": value, "replacement": replacement}
            if replacer:
                step["replacer"] = replacer
            add(item_id, step)

        rep("replace_value_whole_cell", "ab", "Z")
        rep("replace_value_whole_cell_empty_replacement", "ab", "")
        rep("replace_value_other_case", "AB", "Z")
        rep("replace_value_blank_target", "", "Z")
        rep("replace_value_null_replacement", "ab", None)
        rep("replace_value_null_target", None, "Z")
        rep("replace_value_number_target", 5, "Z")
        rep("replace_value_bool_replacement", "ab", True)
        rep("replace_value_regex_chars", "(ab)*", "r")
        rep("replace_text_substring", "ab", "Z", "text")
        rep("replace_text_overlapping", "aa", "X", "text")
        rep("replace_text_repeated_search_in_replacement", "a", "aa", "text")
        rep("replace_text_empty_replacement", "a", "", "text")
        rep("replace_text_other_case", "AB", "Z", "text")
        rep("replace_text_not_present", "zzz", "Z", "text")
        rep("replace_text_backslash", "\\", "/", "text")
        rep("replace_text_quote", "'", "''", "text")
        rep("replace_text_dot", ".", "!", "text")
        rep("replace_text_regex_star", "(ab)*", "r", "text")
        rep("replace_text_empty_search", "", "Z", "text")
        rep("replace_text_null_replacement", "ab", None, "text")
        rep("replace_value_missing_col", "ab", "Z", column="missing_xyz")
        rep("replace_text_missing_col", "ab", "Z", "text", column="missing_xyz")
        if "num_clean" in h:
            rep("replace_text_in_number_column", "1", "9", "text", column="num_clean")
        add("replace_error_values_identity", {"op": "replace_error_values", "replacements": [["rep_col", "x"]]})
        add("replace_error_values_missing_col", {"op": "replace_error_values", "replacements": [["missing_xyz", "x"]]})

    # --- text transforms
    for column in [c for c in ("word_col", "text_col") if c in h]:
        for op in ("trim_text", "clean_text", "lowercase_text", "uppercase_text", "proper_case_text", "reverse_text"):
            add(f"{op}_{column}", {"op": op, "column": column})
    add("trim_text_missing_col", {"op": "trim_text", "column": "missing_xyz"})

    # --- merge columns
    if {"grp_key", "cat_col", "blank_col"} <= h:
        add("merge_columns_two_dash", {"op": "merge_columns", "columns": ["grp_key", "cat_col"], "separator": "-", "new_name": "merged"})
        add("merge_columns_three_empty_separator", {"op": "merge_columns", "columns": ["cat_col", "blank_col", "grp_key"], "separator": "", "new_name": "merged"})
        add("merge_columns_long_separator", {"op": "merge_columns", "columns": ["grp_key", "blank_col"], "separator": " ::%_'\\ ", "new_name": "merged"})
        add("merge_columns_name_of_selected", {"op": "merge_columns", "columns": ["grp_key", "cat_col"], "separator": ",", "new_name": "cat_col"})
        add("merge_columns_name_collision", {"op": "merge_columns", "columns": ["grp_key", "cat_col"], "separator": ",", "new_name": "blank_col"})
        add("merge_columns_one_column", {"op": "merge_columns", "columns": ["grp_key"], "separator": ",", "new_name": "merged"})
        add("merge_columns_missing_col", {"op": "merge_columns", "columns": ["grp_key", "missing_xyz"], "separator": ",", "new_name": "merged"})

    # --- split column
    if "split_col" in h:
        for name, delimiter in (("pipe", "|"), ("dot", "."), ("double_a", "aa")):
            add(f"split_column_{name}", {"op": "split_column", "column": "split_col", "delimiter": delimiter})
            add(f"split_column_by_each_delimiter_{name}", {"op": "split_column_by_each_delimiter", "column": "split_col", "delimiter": delimiter})
        add("split_column_from_end_pipe", {"op": "split_column", "column": "split_col", "delimiter": "|", "from_end": True})
        add("split_column_from_end_double_a", {"op": "split_column", "column": "split_col", "delimiter": "aa", "from_end": True})
        add("split_column_from_end_ab", {"op": "split_column", "column": "split_col", "delimiter": "ab", "from_end": True})
        add("split_column_empty_delimiter", {"op": "split_column", "column": "split_col", "delimiter": ""})
        add("split_column_missing_col", {"op": "split_column", "column": "missing_xyz", "delimiter": "|"})

    return items


def _d1a_catalog() -> list[dict[str, Any]]:
    """D1a step items: headers, reshaping, split and extract, conditional column. Each names its D1a table."""
    items: list[dict[str, Any]] = []

    def add(item_id: str, step: dict[str, Any], table: str = "d1a") -> None:
        items.append({"id": item_id, "step": step, "table": table, "d1a": True})

    # --- promote and demote headers (the first data row is the header-like row)
    add("d1a_promote_headers", {"op": "promote_headers"})
    add("d1a_promote_headers_not_all_scalars", {"op": "promote_headers", "promote_all_scalars": False})
    add("d1a_promote_headers_empty_table", {"op": "promote_headers"}, "d1a_empty")
    add("d1a_promote_headers_one_row", {"op": "promote_headers"}, "d1a_one_row")
    add("d1a_demote_headers", {"op": "demote_headers"})
    add("d1a_demote_headers_one_col", {"op": "demote_headers"}, "d1a_one_col")

    # --- transpose
    add("d1a_transpose_table", {"op": "transpose_table"})
    add("d1a_transpose_table_empty", {"op": "transpose_table"}, "d1a_empty")
    add("d1a_transpose_table_one_row", {"op": "transpose_table"}, "d1a_one_row")

    # --- unpivot (both kinds, the order of the listed columns, refusals by name)
    add("d1a_unpivot_columns", {"op": "unpivot_columns", "columns": ["d_num", "d_cat"], "attribute_name": "attr", "value_name": "val"})
    add("d1a_unpivot_columns_listed_order", {"op": "unpivot_columns", "columns": ["d_cat", "d_num"], "attribute_name": "a2", "value_name": "v2"})
    add("d1a_unpivot_columns_all", {"op": "unpivot_columns", "columns": list(D1A_HEADERS), "attribute_name": "attr", "value_name": "val"})
    add("d1a_unpivot_columns_missing_col", {"op": "unpivot_columns", "columns": ["missing_xyz"], "attribute_name": "attr", "value_name": "val"})
    add("d1a_unpivot_columns_empty_list", {"op": "unpivot_columns", "columns": [], "attribute_name": "attr", "value_name": "val"})
    add("d1a_unpivot_columns_clashing_name", {"op": "unpivot_columns", "columns": ["d_num"], "attribute_name": "d_key", "value_name": "val"})
    add("d1a_unpivot_columns_same_names", {"op": "unpivot_columns", "columns": ["d_num"], "attribute_name": "x", "value_name": "x"})
    add("d1a_unpivot_columns_one_row", {"op": "unpivot_columns", "columns": ["d_num"], "attribute_name": "attr", "value_name": "val"}, "d1a_one_row")
    add("d1a_unpivot_columns_empty_table", {"op": "unpivot_columns", "columns": ["d_num"], "attribute_name": "attr", "value_name": "val"}, "d1a_empty")
    add("d1a_unpivot_other_columns", {"op": "unpivot_other_columns", "columns": ["d_key"], "attribute_name": "attr", "value_name": "val"})
    add("d1a_unpivot_other_columns_empty_list", {"op": "unpivot_other_columns", "columns": [], "attribute_name": "attr", "value_name": "val"})
    add("d1a_unpivot_other_columns_all_listed", {"op": "unpivot_other_columns", "columns": list(D1A_HEADERS), "attribute_name": "attr", "value_name": "val"})

    # --- split to rows (empty cells, delimiter-bearing text, empty delimiter, missing column, one column table)
    add("d1a_split_column_to_rows", {"op": "split_column_to_rows", "column": "d_delim", "delimiter": ";"})
    add("d1a_split_column_to_rows_multi_char", {"op": "split_column_to_rows", "column": "d_text", "delimiter": "; "})
    add("d1a_split_column_to_rows_empty_delimiter", {"op": "split_column_to_rows", "column": "d_delim", "delimiter": ""})
    add("d1a_split_column_to_rows_missing_col", {"op": "split_column_to_rows", "column": "missing_xyz", "delimiter": ";"})
    add("d1a_split_column_to_rows_one_col", {"op": "split_column_to_rows", "column": "d_one", "delimiter": ";"}, "d1a_one_col")

    # --- split by positions (characters, unicode, short cells, bounds, refusals by name)
    add("d1a_split_by_positions", {"op": "split_column_by_positions", "column": "d_pos", "positions": [0, 3, 7, 12]})
    add("d1a_split_by_positions_two", {"op": "split_column_by_positions", "column": "d_pos", "positions": [0, 5]})
    add("d1a_split_by_positions_bound", {"op": "split_column_by_positions", "column": "d_pos", "positions": [0, 83886080]})
    add("d1a_split_by_positions_not_zero", {"op": "split_column_by_positions", "column": "d_pos", "positions": [1, 4]})
    add("d1a_split_by_positions_decreasing", {"op": "split_column_by_positions", "column": "d_pos", "positions": [0, 5, 3]})
    add("d1a_split_by_positions_bool", {"op": "split_column_by_positions", "column": "d_pos", "positions": [0, True]})
    add("d1a_split_by_positions_over_bound", {"op": "split_column_by_positions", "column": "d_pos", "positions": [0, 83886081]})
    add("d1a_split_by_positions_one_position", {"op": "split_column_by_positions", "column": "d_pos", "positions": [0]})
    add("d1a_split_by_positions_too_many", {"op": "split_column_by_positions", "column": "d_pos", "positions": list(range(513))})
    add("d1a_split_by_positions_missing_col", {"op": "split_column_by_positions", "column": "missing_xyz", "positions": [0, 3]})

    # --- extract text (before and after, occurrence, missing delimiter, side, empty delimiter, occurrence bound)
    for side in ("before", "after"):
        for occurrence in (0, 1):
            add(f"d1a_extract_{side}_occurrence_{occurrence}", {
                "op": "extract_text_by_delimiter", "column": "d_paren", "delimiter": "(", "side": side, "occurrence": occurrence})
    add("d1a_extract_semicolon_after", {"op": "extract_text_by_delimiter", "column": "d_delim", "delimiter": ";", "side": "after", "occurrence": 0})
    add("d1a_extract_missing_delimiter", {"op": "extract_text_by_delimiter", "column": "d_delim", "delimiter": "|", "side": "before", "occurrence": 0})
    add("d1a_extract_bad_side", {"op": "extract_text_by_delimiter", "column": "d_paren", "delimiter": "(", "side": "middle", "occurrence": 0})
    add("d1a_extract_empty_delimiter", {"op": "extract_text_by_delimiter", "column": "d_paren", "delimiter": "", "side": "before", "occurrence": 0})
    add("d1a_extract_occurrence_bound", {"op": "extract_text_by_delimiter", "column": "d_paren", "delimiter": "(", "side": "before", "occurrence": 100001})
    add("d1a_extract_missing_col", {"op": "extract_text_by_delimiter", "column": "missing_xyz", "delimiter": "(", "side": "before", "occurrence": 0})

    # --- extract between delimiters
    add("d1a_between", {"op": "extract_text_between_delimiters", "column": "d_paren", "start_delimiter": "(", "end_delimiter": ")", "start_occurrence": 0, "end_occurrence": 0})
    add("d1a_between_occurrences", {"op": "extract_text_between_delimiters", "column": "d_paren", "start_delimiter": "(", "end_delimiter": ")", "start_occurrence": 1, "end_occurrence": 0})
    add("d1a_between_missing_start", {"op": "extract_text_between_delimiters", "column": "d_delim", "start_delimiter": "|", "end_delimiter": ";", "start_occurrence": 0, "end_occurrence": 0})
    add("d1a_between_missing_end", {"op": "extract_text_between_delimiters", "column": "d_paren", "start_delimiter": "(", "end_delimiter": "|", "start_occurrence": 0, "end_occurrence": 0})
    add("d1a_between_empty_start", {"op": "extract_text_between_delimiters", "column": "d_paren", "start_delimiter": "", "end_delimiter": ")", "start_occurrence": 0, "end_occurrence": 0})

    # --- conditional column: every operator with every comparison kind (literal, column, null), then the clause rules
    text_ops = ["equals", "not_equals", "contains", "does_not_contain", "begins_with", "does_not_begin_with", "ends_with", "does_not_end_with"]
    numeric_ops = ["greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal"]

    def clause(column: str, op: str, value: str, kind: str, out: str = "hit", out_kind: str = "value") -> dict[str, str]:
        return {"column": column, "operator": op, "test_value": value, "test_value_kind": kind, "output": out, "output_kind": out_kind}

    def cond(clauses: list[dict[str, str]], name: str = "hit_col", else_value: str = "other", else_kind: str = "value") -> dict[str, Any]:
        return {"op": "conditional_column", "name": name, "clauses": clauses, "else_value": else_value, "else_kind": else_kind}

    for op in text_ops:
        for kind, value in (("value", "e"), ("column", "d_cat"), ("null", "")):
            add(f"d1a_cond_{op}_{kind}", cond([clause("d_text", op, value, kind)]))
    for op in numeric_ops:
        # d_clean holds only exact forms; d_clean2 is a second exact column; d_text is text (mixed compare)
        for item_kind, kind, value in (
            ("value", "value", "2"), ("column", "column", "d_clean2"),
            ("column_mixed", "column", "d_text"), ("null", "null", ""),
        ):
            add(f"d1a_cond_{op}_{item_kind}", cond([clause("d_clean", op, value, kind)]))
        # refused by name: a column or literal that SQL does not read like the engine (d_num holds 1e30, 1E+20, ...)
        add(f"d1a_cond_{op}_dirty_column", cond([clause("d_num", op, "2", "value")]))
        add(f"d1a_cond_{op}_dirty_column_right", cond([clause("d_clean", op, "d_num", "column")]))
    add("d1a_cond_greater_than_big_literal", cond([clause("d_clean", "greater_than", "1e30", "value")]))
    add("d1a_cond_greater_than_fraction_literal", cond([clause("d_clean", "greater_than", "0.1234567890123456789", "value")]))
    add("d1a_cond_greater_than_text_literal", cond([clause("d_clean", "greater_than", "abc", "value")]))
    add("d1a_cond_first_match", cond([clause("d_cat", "equals", "A", "value", "first"), clause("d_cat", "equals", "A", "value", "second")]))
    add("d1a_cond_output_column_else_column", cond([clause("d_cat", "equals", "A", "value", "d_key", "column")], else_value="d_text", else_kind="column"))
    add("d1a_cond_64_clauses", cond([clause("d_cat", "equals", c, "value") for c in [f"v{i}" for i in range(64)]]))
    add("d1a_cond_65_clauses", cond([clause("d_cat", "equals", c, "value") for c in [f"v{i}" for i in range(65)]]))
    add("d1a_cond_clashing_name", cond([clause("d_cat", "equals", "A", "value")], name="d_key"))
    add("d1a_cond_missing_col", cond([clause("missing_xyz", "equals", "A", "value")]))
    add("d1a_cond_bad_operator", cond([clause("d_cat", "bogus", "A", "value")]))
    add("d1a_cond_bad_else_kind", cond([clause("d_cat", "equals", "A", "value")], else_kind="bogus"))
    add("d1a_cond_empty_clauses", cond([]))
    add("d1a_cond_blank_name", cond([clause("d_cat", "equals", "A", "value")], name=" "))
    add("d1a_cond_one_row", cond([clause("d_cat", "equals", "A", "value")]), "d1a_one_row")
    add("d1a_cond_empty_table", cond([clause("d_cat", "equals", "A", "value")]), "d1a_empty")

    # --- sequences: each step runs on the previous step's output (materialised in the store)
    def seq(item_id: str, steps: list[dict[str, Any]], table: str = "d1a") -> None:
        items.append({"id": item_id, "step": {"op": "sequence"}, "sequence": steps, "table": table, "d1a": True})

    seq("d1a_seq_split_then_unpivot", [
        {"op": "split_column_to_rows", "column": "d_delim", "delimiter": ";"},
        {"op": "unpivot_columns", "columns": ["d_clean"], "attribute_name": "attr", "value_name": "val"},
    ])
    seq("d1a_seq_unpivot_then_promote", [
        {"op": "unpivot_columns", "columns": ["d_num", "d_cat"], "attribute_name": "attr", "value_name": "val"},
        {"op": "promote_headers"},
    ])
    seq("d1a_seq_transpose_then_promote", [{"op": "transpose_table"}, {"op": "promote_headers"}])
    seq("d1a_seq_extract_then_conditional", [
        {"op": "extract_text_by_delimiter", "column": "d_paren", "delimiter": "(", "side": "before", "occurrence": 0},
        cond([clause("d_paren", "equals", "", "value")], name="blank_paren"),
    ])
    seq("d1a_seq_positions_then_conditional", [
        {"op": "split_column_by_positions", "column": "d_pos", "positions": [0, 3]},
        cond([clause("d_pos.1", "begins_with", "ab", "value")], name="ab_start"),
    ])
    return items


CONVERT_TARGET_TYPES = ["decimal_number", "whole_number", "number", "boolean", "date", "datetime", "time", "text", "any"]


def _d1b_catalog() -> list[dict[str, Any]]:
    """D1b step items (slice 5). Each names its D1b table (`generate_d1b_csv`); items carry "d1b": True."""
    items: list[dict[str, Any]] = []

    def add(item_id: str, step: dict[str, Any], table: str = "d1b", **extra: Any) -> None:
        items.append({"id": item_id, "step": step, "table": table, "d1b": True, **extra})

    # --- convert_type: every column to every type the engine accepts
    for column in D1B_HEADERS:
        for target in CONVERT_TARGET_TYPES:
            add(f"d1b_conv_{column}_{target}", {"op": "convert_type", "column": column, "type": target})
    add("d1b_conv_missing_col", {"op": "convert_type", "column": "missing_xyz", "type": "whole_number"})
    add("d1b_conv_bad_type", {"op": "convert_type", "column": "b_num", "type": "bogus"})
    add("d1b_conv_extra_field", {"op": "convert_type", "column": "b_num", "type": "whole_number", "culture": "en-US"})
    add("d1b_conv_empty_table", {"op": "convert_type", "column": "b_num", "type": "decimal_number"}, "d1b_empty")
    add("d1b_conv_one_row", {"op": "convert_type", "column": "b_round", "type": "whole_number"}, "d1b_one_row")
    add("d1b_conv_blank_cells_number", {"op": "convert_type", "column": "b_num", "type": "decimal_number"}, "d1b_blank")
    add("d1b_conv_blank_cells_date", {"op": "convert_type", "column": "b_date", "type": "date"}, "d1b_blank")

    # --- convert_type_using_locale: en-US numbers and dates (other cultures are named refusals)
    for column in ["b_num", "b_exp", "b_long", "b_tiny", "b_round", "b_date", "b_dt", "b_grp"]:
        for target in ["decimal_number", "whole_number", "date", "datetime", "time"]:
            add(f"d1b_loc_{column}_{target}", {"op": "convert_type_using_locale", "column": column, "type": target, "culture": "en-US"})
    add("d1b_loc_culture_underscore", {"op": "convert_type_using_locale", "column": "b_num", "type": "decimal_number", "culture": "en_us"})
    add("d1b_loc_culture_de", {"op": "convert_type_using_locale", "column": "b_num", "type": "decimal_number", "culture": "de-DE"})
    add("d1b_loc_culture_bogus", {"op": "convert_type_using_locale", "column": "b_num", "type": "decimal_number", "culture": "bogus"})
    add("d1b_loc_padded_column", {"op": "convert_type_using_locale", "column": " b_round ", "type": "whole_number", "culture": "en-US"})
    add("d1b_loc_missing_col", {"op": "convert_type_using_locale", "column": "missing_xyz", "type": "whole_number", "culture": "en-US"})
    add("d1b_loc_bad_type", {"op": "convert_type_using_locale", "column": "b_num", "type": "text", "culture": "en-US"})
    add("d1b_loc_empty_table", {"op": "convert_type_using_locale", "column": "b_num", "type": "decimal_number", "culture": "en-US"}, "d1b_empty")
    add("d1b_loc_blank_cells", {"op": "convert_type_using_locale", "column": "b_num", "type": "decimal_number", "culture": "en-US"}, "d1b_blank")

    def seq(item_id: str, steps: list[dict[str, Any]], table: str = "d1b") -> None:
        items.append({"id": item_id, "step": {"op": "sequence"}, "sequence": steps, "table": table, "d1b": True})

    # --- sparse rows (Part A step 5) and table pass-through (step 6)
    add("d1b_sparse_top_generated", {"op": "remove_sparse_top_rows"}, "d1b_sparse")
    add("d1b_sparse_bottom_generated", {"op": "remove_sparse_bottom_rows"}, "d1b_sparse")
    add("d1b_sparse_top_blank", {"op": "remove_sparse_top_rows"}, "d1b_blank")
    add("d1b_sparse_bottom_blank", {"op": "remove_sparse_bottom_rows"}, "d1b_blank")
    add("d1b_sparse_top_one_row", {"op": "remove_sparse_top_rows"}, "d1b_one_row")
    add("d1b_sparse_bottom_empty", {"op": "remove_sparse_bottom_rows"}, "d1b_empty")
    add("d1b_sparse_top_extra_field", {"op": "remove_sparse_top_rows", "column": "b_num"})
    add("d1b_pass_through", {"op": "table_pass_through"})
    add("d1b_pass_through_empty", {"op": "table_pass_through"}, "d1b_empty")

    seq("d1b_seq_keep_then_convert", [
        {"op": "keep_columns", "columns": ["b_round", "b_num"]},
        {"op": "convert_type", "column": "b_round", "type": "whole_number"},
    ])
    seq("d1b_seq_convert_then_trim", [
        {"op": "convert_type", "column": "b_num", "type": "decimal_number"},
        {"op": "trim_text", "column": "b_num"},
    ])
    return items


def inspect_store_columns(
    store: DuckStore | None,
    table_name: str,
    headers: list[str],
) -> dict[str, dict[str, Any]]:
    """Facts about every column, read from the store and decided by the ENGINE's rules.

    Per column: `is_num` (every non-blank cell parses as Decimal(text.strip()), finite),
    `first_bad_number` ((row, text) of the first non-blank cell that does not, in load order),
    `date_kind_first_row` ({'naive'|'aware': first row} over cells the engine's date parse accepts),
    `num_sql_exact` / `date_sql_exact` (the SQL expression gives the same exact value as the engine for
    every distinct cell, measured in the store; if not, the tool refuses that step by name).
    Uses the public store.execute() only.
    """
    meta: dict[str, dict[str, Any]] = {}
    # Names that cannot be quoted safely get no facts; the step loop refuses them by name.
    headers = [h for h in headers if unsafe_header_reason(h) is None]
    if not headers or store is None:
        return meta
    col_list = ", ".join(f'"{h}"' for h in headers)
    scan = store.execute(f'SELECT {col_list} FROM "{table_name}" ORDER BY {_RN}')
    for idx, h in enumerate(headers):
        values = [r[idx] for r in scan]
        distinct = {v for v in values if v not in (None, "")}
        numbers = {v: engine_number(v) for v in distinct}
        dates = {v: engine_date(v) for v in distinct}
        first_bad: tuple[int, str] | None = None
        kind_rows: dict[str, int] = {}
        for n, v in enumerate(values, 1):
            if v in (None, ""):
                continue
            if first_bad is None and numbers[v] is None:
                first_bad = (n, v)
            parsed = dates[v]
            if parsed is not None and parsed[0] not in kind_rows:
                kind_rows[parsed[0]] = n
        entry: dict[str, Any] = {
            "is_num": first_bad is None,
            "first_bad_number": first_bad,
            "date_kind_first_row": kind_rows,
            "num_sql_exact": True,
            "date_sql_exact": True,
            # D0h: ASCII-only column (guards the Unicode case rules), and the exponent facts of the
            # engine's aggregate precision rule over the non-zero numbers of the column.
            "ascii_only": all(v.isascii() for v in distinct),
            "num_max_adjusted": None,
            "num_min_exponent": None,
            "num_abs_sum": None,
        }
        if first_bad is None:
            with localcontext() as ctx:
                ctx.prec = 400
                # upper bound of any group sum or pair of values: the sum of every cell's absolute value
                entry["num_abs_sum"] = sum((abs(numbers[v]) for v in values if v not in (None, "")), Decimal(0))
            non_zero = [n for n in numbers.values() if n is not None and n]
            if non_zero:
                entry["num_max_adjusted"] = max(n.adjusted() for n in non_zero)
                entry["num_min_exponent"] = min(n.as_tuple().exponent for n in non_zero)
        non_blank = f'"{h}" IS NOT NULL AND "{h}" != \'\''
        entry["num_cast_agrees"] = True
        if distinct:
            pairs = store.execute(f'SELECT DISTINCT "{h}", {sql_num_expr(h)} FROM "{table_name}" WHERE {non_blank}')
            for text, sql_value in pairs:
                py_value = numbers[text]
                if py_value is None:
                    agrees = sql_value is None  # the SQL must not read a number the engine rejects
                else:
                    agrees = sql_value is not None and Decimal(sql_value) == py_value and decimal_literal(py_value) is not None
                if not agrees:
                    entry["num_cast_agrees"] = False
                    break
            if first_bad is None:
                entry["num_sql_exact"] = entry["num_cast_agrees"]
        if kind_rows:
            pairs = store.execute(f'SELECT DISTINCT "{h}", {sql_dt_expr(h)} FROM "{table_name}" WHERE {non_blank}')
            for text, ts in pairs:
                parsed = dates[text]
                if parsed is None:
                    same = ts is None
                elif parsed[0] == "naive":
                    same = ts is not None and ts == parsed[1]
                else:
                    same = False
                if not same:
                    entry["date_sql_exact"] = False
                    break
        meta[h] = entry
    return meta


# ---------------------------------------------------------------- D0h: group by, replace, text, merge, split

GROUP_DECIMAL_OPS = {"sum", "average", "median"}
PYTHON_PRECISION = 28  # the engine's minimum aggregate precision (`_aggregate_precision`)
DECIMAL_INTEGER_DIGITS = 20  # DECIMAL(38,18) holds 20 integer digits
NON_ASCII_CASE_REASON = (
    "engine uses Python str case rules (full Unicode: final sigma, ß to SS, İ to i + U+0307, ŉ, ﬁ); "
    "DuckDB lower/upper map one code point at a time and differ on those characters"
)


def missing_column_refusal(name: str) -> Refusal:
    return Refusal(f"Column {name!r} does not exist.", expected_error=f"Column {name!r} does not exist.")


def canon_decimal_text(text: str | None) -> str | None:
    """Plain digits of a decimal cell without trailing zeros: the value, not the engine's exponent form.

    The engine returns Decimal results with the exponent Python arithmetic gives ('4.00', '1E+3');
    the SQL gives a fixed scale. Both sides are compared as exact values through this one function.
    """
    if text is None:
        return None
    try:
        number = Decimal(text)
    except ArithmeticError:
        return text
    plain = format(number, "f")
    if "." in plain:
        plain = plain.rstrip("0").rstrip(".")
    return "0" if plain in ("-0", "") else plain


def divide_pair_text(text: str | None) -> str | None:
    """SQL gives an average or median as 'exact numerator/denominator'; divide like the engine (28 digits)."""
    if text is None or "/" not in text:
        return text
    numerator, denominator = text.split("/")
    with localcontext() as ctx:
        ctx.prec = PYTHON_PRECISION
        return str(Decimal(numerator) / Decimal(denominator))


def canonicalize_group_by_rows(
    step: dict[str, Any],
    engine_rows: list[list[str | None]],
    store_rows: list[list[str | None]],
) -> tuple[list[list[str | None]], list[list[str | None]]]:
    """Compare sum, average and median columns as exact values (see `canon_decimal_text`)."""
    first = len(step["columns"])
    decimal_at = [first + i for i, a in enumerate(step["aggregations"]) if a["operation"] in GROUP_DECIMAL_OPS]
    pair_at = [first + i for i, a in enumerate(step["aggregations"]) if a["operation"] in {"average", "median"}]

    def fix(rows: list[list[str | None]], divide: bool) -> list[list[str | None]]:
        out = []
        for row in rows:
            row = list(row)
            for k in decimal_at:
                value = divide_pair_text(row[k]) if divide and k in pair_at else row[k]
                row[k] = canon_decimal_text(value)
            out.append(row)
        return out

    return fix(engine_rows, False), fix(store_rows, True)


def group_by_first_data_error(store: DuckStore, table_name: str, step: dict[str, Any]) -> str | None:
    """The first engine error of a group by over non-numeric text, found the way the engine meets it.

    The engine builds the groups in first-seen order, then for each group and each aggregation in order parses
    the group's non-blank cells; the first cell that is not a finite number aborts with its row in the table.
    """
    keys = step["columns"]
    aggs = step["aggregations"]
    needed = list(dict.fromkeys(keys + [a["column"] for a in aggs if a["operation"] in GROUP_DECIMAL_OPS]))
    col_list = ", ".join(f'"{c}"' for c in needed)
    at = {c: i for i, c in enumerate(needed)}
    groups: dict[tuple[Any, ...], list[tuple[int, tuple[Any, ...]]]] = {}
    for n, row in enumerate(store.execute(f'SELECT {col_list} FROM "{table_name}" ORDER BY {_RN}'), 1):
        groups.setdefault(tuple(row[at[k]] for k in keys), []).append((n, row))
    for members in groups.values():
        for aggregate in aggs:
            if aggregate["operation"] not in GROUP_DECIMAL_OPS:
                continue
            column = aggregate["column"]
            for n, row in members:
                value = row[at[column]]
                if value not in (None, "") and engine_number(value) is None:
                    return f"Value {value!r} in row {n} of column {column!r} is not a valid number."
    return None


GROUP_ROW_OPERATIONS = {"count_rows", "count_distinct_rows"}
GROUP_COLUMN_OPERATIONS = {"sum", "average", "median", "min", "max", "count_distinct_values"}


def _group_by_validation_refusal(step: dict[str, Any], headers: list[str]) -> Refusal | None:
    """Mirror the engine's order: group columns, duplicates, aggregations, each aggregation's shape, output names."""
    keys = step["columns"]
    if not isinstance(keys, list) or not keys or any(not isinstance(k, str) or not k.strip() for k in keys):
        return Refusal("The group step needs one or more group columns.", expected_error="needs one or more group columns.")
    if len(set(keys)) != len(keys):
        return Refusal("duplicate group column", expected_error="contains a duplicate group column.")
    aggregations = step["aggregations"]
    if not isinstance(aggregations, list) or not aggregations:
        return Refusal("The group step needs one or more aggregations.", expected_error="needs one or more aggregations.")
    outputs = set(keys)
    for number, aggregate in enumerate(aggregations, 1):
        if not isinstance(aggregate, dict):
            return Refusal(f"Aggregation {number} in step 1 must be an object.", expected_error=f"Aggregation {number} in step 1 must be an object.")
        operation = aggregate.get("operation")
        if operation not in GROUP_ROW_OPERATIONS | GROUP_COLUMN_OPERATIONS:
            return Refusal(f"Aggregation {number} in step 1 has an unsupported operation.", expected_error=f"Aggregation {number} in step 1 has an unsupported operation.")
        expected = {"operation", "new_name"} | ({"column"} if operation in GROUP_COLUMN_OPERATIONS else set())
        if not expected <= set(aggregate) <= expected | {"m_type"} or any(not isinstance(v, str) for v in aggregate.values()):
            return Refusal(f"Aggregation {number} in step 1 has missing or invalid fields.", expected_error=f"Aggregation {number} in step 1 has missing or invalid fields.")
        name = aggregate["new_name"].strip()
        if name in outputs:
            return Refusal(
                f"output column {name!r} conflicts",
                expected_error=f"Group output column {name!r} conflicts with another output column.",
            )
        outputs.add(name)
    for key in keys:
        if key not in headers:
            return missing_column_refusal(key)
    for aggregate in step["aggregations"]:
        if "column" in aggregate and aggregate["column"] not in headers:
            return missing_column_refusal(aggregate["column"])
    return None


def _map_group_by(
    step: dict[str, Any],
    headers: list[str],
    t_q: str,
    table_name: str,
    total_rows: int,
    overrides: dict[str, Any],
    col_meta: dict[str, dict[str, Any]] | None,
    store: DuckStore | None,
) -> tuple[str, list[str]] | Refusal:
    """Group by: exact keys in first-seen order, aggregates as the engine's `_aggregate_group`.

    Rule table (engine `_group_by`, `_aggregate_group`, `_aggregate_precision`):
      key cell       exact text (cell_key), case-sensitive, '' is a value, '1' and '1.0' are two keys;
                     SQL GROUP BY on VARCHAR is byte-exact, so the same.
      group order    first seen (smallest "__rn" of the group).
      count_rows / count_distinct_rows (all columns) / count_distinct_values (blank counts as a value):
                     COUNT(*), COUNT(DISTINCT ROW(all columns)), COUNT(DISTINCT col).
      sum            Decimal(strip) of every non-blank cell, exact (precision = max(28, needed)); SQL SUM of
                     DECIMAL(38,18), refused when the column's absolute values add up to 10^20 or more.
      average/median Exact sum (or the two middle values) divided by the count (or 2) at 28 digits. DuckDB divides
                     DECIMAL by DECIMAL in DOUBLE (measured), so the SQL returns the exact numerator and the
                     denominator and `divide_pair_text` divides them; refused when the engine's precision rule
                     needs more than 28 digits for the column.
      min/max        Non-blank cells; all numeric: by value, the first of equal values; else by Python casefold
                     of the text (SQL lower(), equal only for ASCII, so non-ASCII text columns are refused).
      all blank      None (SQL NULL) for sum, average, median, min, max.
      non-numeric    sum, average, median over a non-number abort with the engine's text, found by
                     `group_by_first_data_error`.
      error cells    cannot occur in CSV data (the engine aborts on an error key; not reachable here).
    """
    refusal = _group_by_validation_refusal(step, headers)
    if refusal is not None:
        return refusal
    keys = step["columns"]
    aggs = step["aggregations"]
    meta = col_meta or {}
    for aggregate in aggs:
        reason = unsafe_header_reason(aggregate["new_name"].strip())
        if reason:
            return Refusal(reason)
    decimal_aggs = [a for a in aggs if a["operation"] in GROUP_DECIMAL_OPS]
    if any("is_num" not in meta.get(a["column"], {}) for a in decimal_aggs):
        return Refusal("No column facts for a numeric aggregate column.")
    if any(not meta[a["column"]]["is_num"] for a in decimal_aggs):
        if store is None:
            return Refusal("The first non-numeric cell cannot be located without the store.")
        message = group_by_first_data_error(store, table_name, step)
        if message is None:
            return Refusal("A numeric aggregate column holds a non-number but the engine would not stop.")
        return Refusal(message, expected_error=message)

    digits_n = len(str(max(total_rows, 1)))
    for aggregate in aggs:
        operation = aggregate["operation"]
        if operation in GROUP_DECIMAL_OPS or operation in {"min", "max"}:
            fact = meta.get(aggregate["column"])
            if fact is None:
                return Refusal(f"No column facts for column {aggregate['column']!r}.")
            if not fact.get("num_cast_agrees", True) and not overrides.get("mutant_cast_agree_refusal_off"):
                return Refusal(
                    f"Column {aggregate['column']!r} holds numeric text SQL does not read exactly like the engine "
                    "(more than 18 decimals, 20+ integer digits, or a form only one side accepts)."
                )
        if operation in GROUP_DECIMAL_OPS:
            fact = meta[aggregate["column"]]
            max_adj, min_exp = fact.get("num_max_adjusted"), fact.get("num_min_exponent")
            abs_sum = fact.get("num_abs_sum")
            if (
                abs_sum is not None
                and abs_sum >= Decimal(10) ** DECIMAL_INTEGER_DIGITS
                and not overrides.get("mutant_abs_sum_refusal_off")
            ):
                return Refusal(
                    f"A {operation} over column {aggregate['column']!r} could leave DECIMAL(38,18): "
                    "the cells' absolute values add up to 10^20 or more."
                )
            if operation in {"average", "median"} and max_adj is not None:
                required = max_adj - min_exp + digits_n + 2
                if required > PYTHON_PRECISION:
                    return Refusal(
                        f"The engine's aggregate precision rule needs {required} digits for column "
                        f"{aggregate['column']!r}; the harness division mirrors 28."
                    )
        if operation in {"min", "max"}:
            fact = meta[aggregate["column"]]
            if not fact.get("is_num") and not fact.get("ascii_only"):
                return Refusal(
                    f"{operation} of non-numeric text uses Python casefold; SQL lower() differs for non-ASCII; "
                    f"column {aggregate['column']!r} holds non-ASCII text."
                )

    selects: list[str] = []
    if overrides.get("mutant_group_key_casefold"):
        group_exprs = [f'lower("{k}")' for k in keys]
    elif overrides.get("mutant_group_blank_key_merged"):
        group_exprs = [f'CASE WHEN trim("{k}") = \'\' THEN \'\' ELSE "{k}" END' for k in keys]
    else:
        group_exprs = [f'"{k}"' for k in keys]
    if group_exprs == [f'"{k}"' for k in keys]:
        selects.extend(f'"{k}"' for k in keys)
    else:
        selects.extend(f'arg_min("{k}", {_RN}) AS "{k}"' for k in keys)

    for aggregate in aggs:
        operation = aggregate["operation"]
        name = aggregate["new_name"].strip()
        column = aggregate.get("column")
        if operation == "count_rows":
            expr = "COUNT(*)"
        elif operation == "count_distinct_rows":
            expr = "COUNT(DISTINCT ROW(" + ", ".join(f'"{h}"' for h in headers) + "))"
        elif operation == "count_distinct_values":
            if overrides.get("mutant_group_count_skips_blank"):
                expr = f"COUNT(DISTINCT NULLIF(\"{column}\", ''))"
            else:
                expr = f'COUNT(DISTINCT "{column}")'
        else:
            num = sql_num_expr(column)
            non_blank = f'"{column}" <> \'\''
            if operation == "sum":
                expr = f"SUM({num})"
            elif operation == "average":
                if overrides.get("mutant_group_average_float"):
                    expr = f"CAST(AVG({num}) AS VARCHAR)"
                else:
                    expr = f"CASE WHEN COUNT({num}) = 0 THEN NULL ELSE CAST(SUM({num}) AS VARCHAR) || '/' || CAST(COUNT({num}) AS VARCHAR) END"
            elif operation == "median":
                ordered = f"list_sort(list({num}) FILTER (WHERE {num} IS NOT NULL))"
                n_vals = f"COUNT({num})"
                expr = (
                    f"CASE WHEN {n_vals} = 0 THEN NULL "
                    f"WHEN {n_vals} % 2 = 1 THEN CAST({ordered}[({n_vals} + 1) // 2] AS VARCHAR) || '/1' "
                    f"ELSE CAST({ordered}[{n_vals} // 2] + {ordered}[{n_vals} // 2 + 1] AS VARCHAR) || '/2' END"
                )
            else:  # min / max over non-blank cells, numeric when every non-blank cell of the group is a number
                pick = "arg_min" if operation == "min" else "arg_max"
                num_key = f"row({num}, {_RN})" if operation == "min" else f"row({num}, -{_RN})"
                text_key = f'row(lower("{column}"), {_RN})' if operation == "min" else f'row(lower("{column}"), -{_RN})'
                expr = (
                    f"CASE WHEN COUNT(*) FILTER (WHERE {non_blank}) = 0 THEN NULL "
                    f"WHEN bool_and({num} IS NOT NULL) FILTER (WHERE {non_blank}) "
                    f'THEN {pick}("{column}", {num_key}) FILTER (WHERE {non_blank}) '
                    f'ELSE {pick}("{column}", {text_key}) FILTER (WHERE {non_blank}) END'
                )
        selects.append(f'{expr} AS "{name}"')

    order = ", ".join(f'"{k}"' for k in keys) if overrides.get("mutant_group_order_not_first_seen") else f"MIN({_RN})"
    sql = f"SELECT {', '.join(selects)} FROM {t_q} GROUP BY {', '.join(group_exprs)} ORDER BY {order}"
    return (sql, [*keys, *(a["new_name"].strip() for a in aggs)])


def _map_replace_value(
    step: dict[str, Any], headers: list[str], t_q: str, overrides: dict[str, Any]
) -> tuple[str, list[str]] | Refusal:
    """replace_value. Rule table (engine `replace_value` branch and `_replace_cell_matches_value`):
      value form (default)  a text target replaces a cell only when the WHOLE cell equals it (case-sensitive,
                            no trimming, '' is a blank cell target); a null, number or bool target matches no
                            text cell (the match is by kind); a null replacement writes a null cell.
      text form             Python str.replace on every cell: all non-overlapping left-to-right occurrences,
                            case-sensitive; the search text must be a non-empty string and the replacement a string.
      literals              quotes, %, _, backslash and regex characters are plain text on both sides (SQL
                            replace() and '=' compare text, never a pattern).
    """
    column, value, replacement = step["column"], step["value"], step["replacement"]
    replacer = step.get("replacer")
    if replacer == "text":
        if not isinstance(value, str) or value == "":
            message = "needs a non-empty text value to find."
            return Refusal("ReplaceText search text is empty", expected_error=message)
        if not isinstance(replacement, str):
            return Refusal("ReplaceText needs a text replacement", expected_error="ReplaceText needs a text replacement.")
    if column not in headers:
        return missing_column_refusal(column)
    if replacement is None:
        repl_sql = "NULL"
    elif isinstance(replacement, str):
        repl_sql = sql_str(replacement)
    elif isinstance(replacement, int) and not isinstance(replacement, bool):
        repl_sql = sql_str(str(replacement))
    else:
        return Refusal("A bool, float or decimal replacement keeps its type in the engine; the store cell is text.")
    if isinstance(repl_sql, Refusal):
        return repl_sql
    if replacer == "text":
        old_sql = sql_str(value)
        if isinstance(old_sql, Refusal):
            return old_sql
        if overrides.get("mutant_replace_text_whole_cell"):
            expr = f'CASE WHEN "{column}" = {old_sql} THEN {repl_sql} ELSE "{column}" END'
        elif overrides.get("mutant_replace_case_insensitive"):
            expr = f"replace(lower(\"{column}\"), lower({old_sql}), {repl_sql})"
        else:
            expr = f'replace("{column}", {old_sql}, {repl_sql})'
    elif isinstance(value, str):
        old_sql = sql_str(value)
        if isinstance(old_sql, Refusal):
            return old_sql
        if overrides.get("mutant_replace_value_substring"):
            expr = f'replace("{column}", {old_sql}, {repl_sql})'
        elif overrides.get("mutant_replace_case_insensitive"):
            expr = f'CASE WHEN lower("{column}") = lower({old_sql}) THEN {repl_sql} ELSE "{column}" END'
        else:
            expr = f'CASE WHEN "{column}" = {old_sql} THEN {repl_sql} ELSE "{column}" END'
    else:
        expr = f'"{column}"'  # a null, number or bool target never equals a text cell
    cols = ", ".join(f'{expr} AS "{h}"' if h == column else f'"{h}"' for h in headers)
    return (f"SELECT {cols} FROM {t_q} ORDER BY {_RN}", list(headers))


CLEAN_CC_REGEX = "[\\x00-\\x1f\\x7f-\\x{9f}]"  # Unicode category Cc, the engine's clean_text set


def _map_text_transform(
    step: dict[str, Any],
    headers: list[str],
    t_q: str,
    overrides: dict[str, Any],
    col_meta: dict[str, dict[str, Any]] | None,
) -> tuple[str, list[str]] | Refusal:
    """trim, clean, lowercase, uppercase, proper case, reverse. Rule table (engine text branches):
      trim_text        str.strip(): removes every character with str.isspace() (PY_WHITESPACE); SQL trim with that set.
      clean_text       removes every character of Unicode category Cc (U+0000-001F, U+007F-009F); SQL regex class.
      lowercase_text   str.lower(): full Unicode (final sigma, İ to two code points).
      uppercase_text   str.upper(): full Unicode (ß to SS, ŉ, ﬁ).
      proper_case_text str.title(): a cased letter after a non-letter starts a word (digits and ' count as
                       non-letters), every other cased letter is lowered.
      reverse_text     reverses code points (value[::-1]), combining marks and flags included.
      Mapped to SQL: trim, clean, reverse (all text), and lower, upper, proper case only on ASCII-only columns.
      Refused by name on non-ASCII columns for lower, upper, proper case (DuckDB differs; see the probe test).
    """
    op = step["op"]
    column = step["column"]
    if column not in headers:
        return missing_column_refusal(column)
    c = f'"{column}"'
    if op == "trim_text":
        ws = sql_str(PY_WHITESPACE)
        expr = f"trim({c})" if overrides.get("mutant_trim_spaces_only") else f"trim({c}, {ws})"
    elif op == "clean_text":
        expr = f"regexp_replace({c}, '{CLEAN_CC_REGEX}', '', 'g')"
    elif op == "reverse_text":
        expr = f"CASE WHEN {c} IS NULL THEN NULL ELSE COALESCE(array_to_string(list_reverse(regexp_extract_all({c}, '(?s).')), ''), '') END"
    else:
        fact = (col_meta or {}).get(column)
        if fact is None:
            return Refusal(f"No column facts for column {column!r}.")
        unguarded = op == "lowercase_text" and overrides.get("mutant_lower_non_ascii")
        if not fact.get("ascii_only") and not unguarded:
            return Refusal(f"{NON_ASCII_CASE_REASON}; column {column!r} holds non-ASCII text.")
        if op == "lowercase_text":
            expr = f"lower({c})"
        elif op == "uppercase_text":
            expr = f"upper({c})"
        else:
            expr = (
                f"CASE WHEN {c} IS NULL THEN NULL ELSE COALESCE(array_to_string(list_transform(regexp_extract_all({c}, '(?s).'), "
                f"(x, i) -> CASE WHEN i > 1 AND regexp_matches(regexp_extract_all({c}, '(?s).')[i - 1], '^[A-Za-z]$') "
                f"THEN lower(x) ELSE upper(x) END), ''), '') END"
            )
    cols = ", ".join(f'{expr} AS "{h}"' if h == column else f'"{h}"' for h in headers)
    return (f"SELECT {cols} FROM {t_q} ORDER BY {_RN}", list(headers))


def _map_merge_columns(
    step: dict[str, Any], headers: list[str], t_q: str, overrides: dict[str, Any]
) -> tuple[str, list[str]] | Refusal:
    """merge_columns. Rule table (engine `_merge_columns`):
      join order       the order of `columns` as given; the separator goes between neighbours only.
      blank / null     a blank or null cell contributes '' (the separator stays), never skipped.
      position         the merged column sits where the leftmost selected column was; the other selected
                       columns are removed; a new name equal to a selected column is allowed, equal to any
                       other column is an engine error.
      separator        any text (quotes, %, regex characters are plain text).
    """
    columns = step["columns"]
    if not isinstance(columns, list) or len(columns) < 2 or any(not isinstance(c, str) or not c.strip() for c in columns):
        return Refusal("fewer than two merge columns", expected_error="needs at least two columns to merge.")
    columns = [c.strip() for c in columns]  # the engine looks the stripped names up
    if len(set(columns)) != len(columns):
        return Refusal("duplicate merge column", expected_error="contains a duplicate merge column.")
    for name in columns:
        if name not in headers:
            return missing_column_refusal(name)
    new_name = step["new_name"].strip()
    selected = set(columns)
    if new_name in headers and new_name not in selected:
        message = f"Cannot merge columns: output column {new_name!r} already exists."
        return Refusal(message, expected_error=message)
    reason = unsafe_header_reason(new_name)
    if reason:
        return Refusal(reason)
    separator = step["separator"]
    if overrides.get("mutant_merge_separator_off"):
        separator = separator[1:]
    sep_sql = sql_str(separator)
    if isinstance(sep_sql, Refusal):
        return sep_sql
    if overrides.get("mutant_merge_skip_blank"):
        parts = ", ".join(f'"{c}"' for c in columns)
        merged = f"array_to_string(list_filter([{parts}], x -> x <> ''), {sep_sql})"
    else:
        merged = f" || {sep_sql} || ".join(f"COALESCE(\"{c}\", '')" for c in columns)
    first = min(headers.index(c) for c in columns)
    out_headers: list[str] = []
    exprs: list[str] = []
    for index, header in enumerate(headers):
        if index == first:
            out_headers.append(new_name)
            exprs.append(f'{merged} AS "{new_name}"')
        if header not in selected:
            out_headers.append(header)
            exprs.append(f'"{header}"')
    return (f"SELECT {', '.join(exprs)} FROM {t_q} ORDER BY {_RN}", out_headers)


def _map_split_column(
    step: dict[str, Any],
    headers: list[str],
    t_q: str,
    table_name: str,
    overrides: dict[str, Any],
    store: DuckStore | None,
) -> tuple[str, list[str]] | Refusal:
    """split_column (first delimiter, or the last with from_end) and split_column_by_each_delimiter.

    Rule table (engine `_split_column`, `_split_column_by_each_delimiter`):
      delimiter        any non-empty text, matched literally, left to right without overlap (str.partition,
                       str.split); SQL string_split is a literal split too (a regex is never used).
      split_column     two columns '<name>.1' and '<name>.2': text before the first (from_end: last) delimiter and the
                       rest; no delimiter: the whole text and a null; a delimiter at an end gives an empty part.
      each delimiter   one column per part, as many as the LONGEST cell has (at least two), named '<name>.1' ...;
                       a row with fewer parts gets nulls; a blank cell is one empty part. The width is read
                       from the data with SQL before the query is written.
      collision        an output name that already exists is an engine error.
    """
    op = step["op"]
    column, delimiter = step["column"], step["delimiter"]
    if delimiter == "":
        return Refusal("empty delimiter", expected_error="needs a non-empty delimiter.")
    if column not in headers:
        return missing_column_refusal(column)
    delim_sql = sql_str(delimiter)
    if isinstance(delim_sql, Refusal):
        return delim_sql
    c = f'"{column}"'
    if op == "split_column_by_each_delimiter":
        if store is None:
            return Refusal("The split width needs a read of the data; no store given.")
        if overrides.get("mutant_split_width_first_row"):
            width_sql = f'SELECT len(string_split({c}, {delim_sql})) FROM {t_q} ORDER BY {_RN} LIMIT 1'
        else:
            width_sql = f"SELECT max(len(string_split({c}, {delim_sql}))) FROM {t_q}"
        found = store.execute(width_sql)
        longest = found[0][0] if found and found[0][0] is not None else 1
        width = max(2, longest)
        if width > MAX_COLUMNS - len(headers) + 1:
            message = f"Splitting {column!r} exceeds the {MAX_COLUMNS}-column import limit."
            return Refusal(message, expected_error=message)
        row_count = store.execute(f"SELECT COUNT(*) FROM {t_q}")[0][0]
        if row_count * (len(headers) - 1 + width) > MAX_CELLS:
            message = f"Splitting {column!r} exceeds the {MAX_CELLS:,}-cell import limit."
            return Refusal(message, expected_error=message)
    else:
        width = 2
    out_names = [f"{column}.{k}" for k in range(1, width + 1)]
    remaining = [h for h in headers if h != column]
    collision = next((name for name in out_names if name in remaining), None)
    if collision is not None:
        message = f"Cannot split {column!r}: output column {collision!r} already exists."
        return Refusal(message, expected_error=message)
    sp = '"__sp"'
    inner_expr = f"string_split({c}, {delim_sql})"
    if op == "split_column_by_each_delimiter":
        part_exprs = [f"{sp}[{k}]" for k in range(1, width + 1)]
    elif step.get("from_end"):
        # rpartition scans from the right (overlapping delimiters such as 'aa' split differently from the left):
        # split the code point reversal of the text on the reversed delimiter, then reverse the two parts back.
        rev_delim_sql = delim_sql if overrides.get("mutant_split_from_end_same_delim") else sql_str(delimiter[::-1])
        reverse = lambda e: f"COALESCE(array_to_string(list_reverse(regexp_extract_all({e}, '(?s).')), ''), '')"
        inner_expr = f"string_split({reverse(c)}, {rev_delim_sql})"
        part_exprs = [
            f"CASE WHEN len({sp}) > 1 THEN {reverse(f'array_to_string({sp}[2:], {rev_delim_sql})')} ELSE {c} END",
            f"CASE WHEN len({sp}) > 1 THEN {reverse(f'{sp}[1]')} END",
        ]
    else:
        part_exprs = [f"{sp}[1]", f"CASE WHEN len({sp}) > 1 THEN array_to_string({sp}[2:], {delim_sql}) END"]
    out_headers: list[str] = []
    exprs: list[str] = []
    for header in headers:
        if header == column:
            for name, expr in zip(out_names, part_exprs):
                out_headers.append(name)
                exprs.append(f'{expr} AS "{name}"')
        else:
            out_headers.append(header)
            exprs.append(f'"{header}"')
    inner = f'SELECT *, {inner_expr} AS {sp} FROM {t_q}'
    return (f"SELECT {', '.join(exprs)} FROM ({inner}) ORDER BY {_RN}", out_headers)


def _map_promote_headers(
    step: dict[str, Any], headers: list[str], t_q: str, store: DuckStore | None, overrides: dict[str, Any]
) -> tuple[str, list[str]] | Refusal:
    if store is None:
        return Refusal("DuckStore required to map promote_headers.")
    # The engine's shape rule first (`_validate_step`), then its apply rule.
    promote_all = step.get("promote_all_scalars", True)
    if not isinstance(promote_all, bool):
        message = "Transformation step 1 PromoteAllScalars setting must be Boolean."
        return Refusal(message, expected_error=message)
    col_list = ", ".join(f'"{h}"' for h in headers)
    rows = store.execute(f"SELECT {_RN}, {col_list} FROM {t_q} ORDER BY {_RN} LIMIT 1")
    if not rows:
        message = "Cannot use the first row as headers because the table has no data rows."
        return Refusal(message, expected_error=message)
    min_rn = rows[0][0]
    first_row_values = [normalize_cell(v) for v in rows[0][1:]]
    # Engine (`_promote_headers`): with promote_all_scalars a NULL is cell_to_text(None) == '' (then 'Column N');
    # without it a NULL is 'Column N' and text is kept.
    header_values: list[str] = []
    for i, v in enumerate(first_row_values):
        if promote_all:
            header_values.append("" if v is None else v)
        else:
            header_values.append(f"Column{i + 1}" if v is None else v)
    promoted = normalize_promoted_headers(header_values, len(headers))
    for name in promoted:
        unsafe = unsafe_header_reason(name)
        if unsafe:
            return Refusal(unsafe)
    select_items = [f'"{old}" AS "{new}"' for old, new in zip(headers, promoted)]
    col_select = ", ".join(select_items)
    where_clause = "" if overrides.get("mutant_promote_keeps_first_row") else f"WHERE {_RN} > {min_rn}"
    sql = f"SELECT {col_select} FROM {t_q} {where_clause} ORDER BY {_RN}"
    return (sql, promoted)


def _map_demote_headers(
    step: dict[str, Any], headers: list[str], t_q: str, overrides: dict[str, Any]
) -> tuple[str, list[str]] | Refusal:
    n = len(headers)
    offset = 1 if overrides.get("mutant_demote_names_off_by_one") else 0
    demoted_names = [f"Column{i + 1 + offset}" for i in range(n)]
    for name in demoted_names:
        unsafe = unsafe_header_reason(name)
        if unsafe:
            return Refusal(unsafe)
    header_vals = [sql_str(h) for h in headers]
    for hv in header_vals:
        if isinstance(hv, Refusal):
            return hv
    header_select = ", ".join(f'{val} AS "{name}"' for val, name in zip(header_vals, demoted_names))
    data_select = ", ".join(f'"{old}" AS "{name}"' for old, name in zip(headers, demoted_names))
    demoted_cols = ", ".join(f'"{name}"' for name in demoted_names)
    sql = (
        f"SELECT {demoted_cols} FROM ("
        f"  SELECT -1 AS _demote_rn, {header_select} "
        f"  UNION ALL "
        f"  SELECT {_RN} AS _demote_rn, {data_select} FROM {t_q}"
        f") ORDER BY _demote_rn"
    )
    return (sql, demoted_names)


def _map_transpose_table(
    step: dict[str, Any], headers: list[str], t_q: str, total_rows: int, overrides: dict[str, Any]
) -> tuple[str, list[str]] | Refusal:
    if total_rows == 0:
        message = "Cannot transpose a table with no data rows."
        return Refusal(message, expected_error=message)
    if total_rows > MAX_COLUMNS:
        message = f"Transposing exceeds the {MAX_COLUMNS}-column import limit."
        return Refusal(message, expected_error=message)
    if len(headers) * total_rows > MAX_CELLS:
        message = f"Transposing exceeds the {MAX_CELLS:,}-cell import limit."
        return Refusal(message, expected_error=message)
    out_headers = [f"Column{i + 1}" for i in range(total_rows)]
    for name in out_headers:
        unsafe = unsafe_header_reason(name)
        if unsafe:
            return Refusal(unsafe)
    if overrides.get("mutant_transpose_headers_dropped"):
        col_list = ", ".join(f'"{h}"' for h in out_headers)
        null_cols = ", ".join(f'NULL AS "{h}"' for h in out_headers)
        return (f"SELECT {col_list} FROM (SELECT {null_cols}) WHERE 1=0", out_headers)
    branches = []
    for c_idx, h in enumerate(headers):
        branches.append(f'SELECT {c_idx} AS c_idx, {_RN} AS r_idx, "{h}" AS val FROM {t_q}')
    unnested_sql = " UNION ALL ".join(branches)
    agg_cols = [f'FIRST(val) FILTER (WHERE r_rn = {r_idx}) AS "{name}"' for r_idx, name in enumerate(out_headers)]
    sql = (
        f"WITH numbered AS ("
        f"  SELECT c_idx, (row_number() OVER (PARTITION BY c_idx ORDER BY r_idx) - 1) AS r_rn, val "
        f"  FROM ({unnested_sql})"
        f") "
        f"SELECT {', '.join(agg_cols)} FROM numbered GROUP BY c_idx ORDER BY c_idx"
    )
    return (sql, out_headers)


def _map_unpivot_columns(
    step: dict[str, Any], headers: list[str], t_q: str, unpivot_other: bool, overrides: dict[str, Any]
) -> tuple[str, list[str]] | Refusal:
    # Engine order (`_validate_step`, then `_unpivot_columns`): columns, duplicates, names, names differ,
    # each column exists (in the order listed), at least one pivot column, output-name clash, column limit.
    columns = step.get("columns")
    if not isinstance(columns, list) or not columns or any(not isinstance(c, str) or not c.strip() for c in columns):
        message = "Transformation step 1 needs one or more columns."
        return Refusal(message, expected_error="needs one or more columns.")
    if len(set(columns)) != len(columns):
        message = "Transformation step 1 contains a duplicate column name."
        return Refusal(message, expected_error="contains a duplicate column name.")
    attribute_name = step.get("attribute_name")
    value_name = step.get("value_name")
    if not isinstance(attribute_name, str) or not attribute_name.strip() or not isinstance(value_name, str) or not value_name.strip():
        message = "Transformation step 1 needs both output column names."
        return Refusal(message, expected_error="needs both output column names.")
    attribute_name = attribute_name.strip()
    value_name = value_name.strip()
    if attribute_name == value_name:
        message = "Transformation step 1 output column names must be different."
        return Refusal(message, expected_error="output column names must be different.")
    for c in columns:
        if c not in headers:
            message = f"Column {c!r} does not exist."
            return Refusal(message, expected_error=message)
    selected = set(columns)
    if unpivot_other:
        retained_headers = [h for h in headers if h in selected]
        pivot_headers = [h for h in headers if h not in selected]
    else:
        pivot_headers = [h for h in headers if h in selected]
        retained_headers = [h for h in headers if h not in selected]
    if not pivot_headers:
        message = "Select at least one column to unpivot."
        return Refusal(message, expected_error=message)
    for name in (attribute_name, value_name):
        if name in retained_headers:
            message = f"Cannot unpivot: output column {name!r} already exists."
            return Refusal(message, expected_error=message)
    out_headers = [*retained_headers, attribute_name, value_name]
    if len(out_headers) > MAX_COLUMNS:
        message = f"Unpivoting exceeds the {MAX_COLUMNS}-column import limit."
        return Refusal(message, expected_error=message)
    reserved = [h for h in out_headers if h in {"__rn", "_p_ord"}]
    if reserved:
        return Refusal(f"Output column {reserved[0]!r} clashes with a name the store path uses; not on the store path.")
    for name in out_headers:
        unsafe = unsafe_header_reason(name)
        if unsafe:
            return Refusal(unsafe)
    retained_cols = ", ".join(f'"{h}"' for h in retained_headers)
    prefix = f"{retained_cols}, " if retained_headers else ""
    branches = []
    for p_idx, col in enumerate(pivot_headers):
        col_lit = sql_str(col)
        if isinstance(col_lit, Refusal):
            return col_lit
        where_val = 'IS NOT NULL AND "' + col + '" != \'\'' if overrides.get("mutant_unpivot_drops_blanks") else 'IS NOT NULL'
        branches.append(
            f'SELECT {prefix}{_RN}, {p_idx} AS _p_ord, {col_lit} AS "{attribute_name}", "{col}" AS "{value_name}" '
            f'FROM {t_q} WHERE "{col}" {where_val}'
        )
    union_sql = " UNION ALL ".join(branches)
    order_clause = f"ORDER BY _p_ord, {_RN}" if overrides.get("mutant_unpivot_order_per_column") else f"ORDER BY {_RN}, _p_ord"
    out_cols = ", ".join(f'"{h}"' for h in out_headers)
    sql = f"SELECT {out_cols} FROM ({union_sql}) {order_clause}"
    return (sql, out_headers)


def _map_split_column_to_rows(
    step: dict[str, Any], headers: list[str], t_q: str, overrides: dict[str, Any]
) -> tuple[str, list[str]] | Refusal:
    column = step.get("column")
    delimiter = step.get("delimiter")
    if not isinstance(column, str) or not isinstance(delimiter, str):
        message = "Transformation step 1 values must be strings."
        return Refusal(message, expected_error="values must be strings.")
    if not column.strip():
        message = "Transformation step 1 needs a column name."
        return Refusal(message, expected_error="needs a column name.")
    if not delimiter:
        message = "Transformation step 1 needs a non-empty delimiter."
        return Refusal(message, expected_error="needs a non-empty delimiter.")
    if column not in headers:
        message = f"Column {column!r} does not exist."
        return Refusal(message, expected_error=message)
    reserved = [h for h in headers if h in {"_part", "_parts", "_sub"}]
    if reserved:
        return Refusal(f"Column {reserved[0]!r} clashes with an alias the store path uses for split parts; not on the store path.")
    delim_sql = sql_str(delimiter)
    if isinstance(delim_sql, Refusal):
        return delim_sql
    c = f'"{column}"'
    if overrides.get("mutant_split_to_rows_loses_empty_parts"):
        split_expr = f"list_filter(string_split({c}, {delim_sql}), x -> x != '')"
    else:
        split_expr = f"string_split({c}, {delim_sql})"
    parts_expr = f"CASE WHEN {c} IS NULL THEN [NULL] WHEN {c} = '' THEN [''] ELSE {split_expr} END"
    select_items = [f'"{h}"' if h != column else f'_part AS "{column}"' for h in headers]
    col_list = ", ".join(select_items)
    order_clause = f"ORDER BY {_RN} DESC, _sub ASC" if overrides.get("mutant_reverse_order") else f"ORDER BY {_RN} ASC, _sub ASC"
    sql = (
        f"WITH prep AS ("
        f"  SELECT *, {parts_expr} AS _parts FROM {t_q}"
        f"), "
        f"expanded AS ("
        f"  SELECT *, UNNEST(_parts) AS _part, generate_subscripts(_parts, 1) AS _sub FROM prep"
        f") "
        f"SELECT {col_list} FROM expanded {order_clause}"
    )
    return (sql, list(headers))


def _map_split_column_by_positions(
    step: dict[str, Any], headers: list[str], t_q: str, overrides: dict[str, Any], total_rows: int = 0
) -> tuple[str, list[str]] | Refusal:
    # Engine order (`_validate_step`): column name (then stripped), 2 to 512 positions, whole numbers in range,
    # start at 0, strictly increasing; then the apply rules (column exists, output-name clash, column limit).
    column = step.get("column")
    positions = step.get("positions")
    if not isinstance(column, str) or not column.strip():
        message = "Transformation step 1 needs a column name."
        return Refusal(message, expected_error="needs a column name.")
    if not isinstance(positions, list) or not 2 <= len(positions) <= MAX_COLUMNS:
        message = "Transformation step 1 needs 2 to 512 split positions."
        return Refusal(message, expected_error="needs 2 to 512 split positions.")
    for p in positions:
        if not isinstance(p, int) or isinstance(p, bool) or p < 0 or p > MAX_SPLIT_POSITION:
            message = "Transformation step 1 positions must be whole numbers from 0 to 83,886,080."
            return Refusal(message, expected_error="positions must be whole numbers from 0 to 83,886,080.")
    if positions[0] != 0:
        message = "Transformation step 1 positions must start at 0."
        return Refusal(message, expected_error="positions must start at 0.")
    if any(b <= a for a, b in zip(positions, positions[1:])):
        message = "Transformation step 1 positions must be in strictly increasing order."
        return Refusal(message, expected_error="positions must be in strictly increasing order.")
    column = column.strip()
    if column not in headers:
        message = f"Column {column!r} does not exist."
        return Refusal(message, expected_error=message)
    out_names = [f"{column}.{i + 1}" for i in range(len(positions))]
    remaining_headers = [h for h in headers if h != column]
    collision = next((name for name in out_names if name in remaining_headers), None)
    if collision is not None:
        message = f"Cannot split {column!r}: output column {collision!r} already exists."
        return Refusal(message, expected_error=message)
    c_idx = headers.index(column)
    out_headers = list(headers)
    out_headers[c_idx:c_idx + 1] = out_names
    if len(out_headers) > MAX_COLUMNS:
        message = f"Splitting {column!r} exceeds the {MAX_COLUMNS}-column import limit."
        return Refusal(message, expected_error=message)
    if total_rows * len(out_headers) > MAX_CELLS:
        message = f"Splitting {column!r} exceeds the {MAX_CELLS:,}-cell import limit."
        return Refusal(message, expected_error=message)
    for name in out_names:
        unsafe = unsafe_header_reason(name)
        if unsafe:
            return Refusal(unsafe)
    c = f'"{column}"'
    pos_list = [p + 1 for p in positions] if overrides.get("mutant_positions_off_by_one") else positions
    part_exprs = []
    for start, end in zip(pos_list, pos_list[1:]):
        count = end - start
        part_exprs.append(f'CASE WHEN {c} IS NULL THEN NULL ELSE substr({c}, {1 + start}, {count}) END')
    part_exprs.append(f'CASE WHEN {c} IS NULL THEN NULL ELSE substr({c}, {1 + pos_list[-1]}) END')
    select_items: list[str] = []
    for h in headers:
        if h == column:
            for name, expr in zip(out_names, part_exprs):
                select_items.append(f'{expr} AS "{name}"')
        else:
            select_items.append(f'"{h}"')
    col_list = ", ".join(select_items)
    order_clause = f"ORDER BY {_RN} DESC" if overrides.get("mutant_reverse_order") else f"ORDER BY {_RN}"
    sql = f"SELECT {col_list} FROM {t_q} {order_clause}"
    return (sql, out_headers)


def _map_extract_text_by_delimiter(
    step: dict[str, Any], headers: list[str], t_q: str, store: DuckStore | None, overrides: dict[str, Any]
) -> tuple[str, list[str]] | Refusal:
    column = step.get("column")
    delimiter = step.get("delimiter")
    side = step.get("side")
    occurrence = step.get("occurrence")
    # Engine order (`_validate_step`): column name (then stripped), side, non-empty delimiter, occurrence bound.
    if not isinstance(column, str) or not column.strip():
        message = "Transformation step 1 needs a column name."
        return Refusal(message, expected_error="needs a column name.")
    if not isinstance(side, str) or side not in {"before", "after"}:
        message = "Transformation step 1 must extract text before or after the delimiter."
        return Refusal(message, expected_error="must extract text before or after the delimiter.")
    if not isinstance(delimiter, str) or not delimiter:
        message = "Transformation step 1 needs a non-empty delimiter."
        return Refusal(message, expected_error="needs a non-empty delimiter.")
    if not isinstance(occurrence, int) or isinstance(occurrence, bool) or occurrence < 0 or occurrence > MAX_DELIMITER_OCCURRENCE:
        message = "Transformation step 1 needs a zero-based delimiter occurrence from 0 to 100,000."
        return Refusal(message, expected_error="needs a zero-based delimiter occurrence from 0 to 100,000.")
    column = column.strip()
    if column not in headers:
        message = f"Column {column!r} does not exist."
        return Refusal(message, expected_error=message)
    if store is None:
        return Refusal("DuckStore required to map extract_text_by_delimiter.")
    delim_sql = sql_str(delimiter)
    if isinstance(delim_sql, Refusal):
        return delim_sql
    c = f'"{column}"'
    occ = occurrence + 1 if overrides.get("mutant_occurrence_off_by_one") else occurrence
    missing_check_sql = (
        f'SELECT {_RN} FROM {t_q} '
        f'WHERE {c} IS NOT NULL AND {c} != \'\' AND len(string_split({c}, {delim_sql})) <= {occ + 1} '
        f'ORDER BY {_RN} LIMIT 1'
    )
    missing_rows = store.execute(missing_check_sql)
    if missing_rows and not overrides.get("mutant_missing_delimiter_returns_blank"):
        min_rn = missing_rows[0][0]
        row_idx_rows = store.execute(
            f'SELECT rn FROM (SELECT {_RN}, (row_number() OVER (ORDER BY {_RN})) AS rn FROM {t_q}) WHERE {_RN} = {min_rn}'
        )
        row_idx = row_idx_rows[0][0] if row_idx_rows else min_rn + 1
        message = f"Could not find zero-based delimiter occurrence {occurrence} in row {row_idx} of column {column!r}."
        return Refusal(message, expected_error=message)
    effective_side = "after" if (side == "before" and overrides.get("mutant_extract_side_swapped")) else "before" if (side == "after" and overrides.get("mutant_extract_side_swapped")) else side
    delim_len = f"length({delim_sql})"
    prefix_len = f"length(list_aggregate(list_slice(string_split({c}, {delim_sql}), 1, {occ + 1}), 'string_agg', {delim_sql}))"
    if effective_side == "before":
        extract_expr = f"list_aggregate(list_slice(string_split({c}, {delim_sql}), 1, {occ + 1}), 'string_agg', {delim_sql})"
    else:
        extract_expr = f"substr({c}, {prefix_len} + {delim_len} + 1)"
    final_expr = f"CASE WHEN {c} IS NULL THEN NULL WHEN {c} = '' THEN '' ELSE {extract_expr} END"
    select_items = [f'{final_expr} AS "{h}"' if h == column else f'"{h}"' for h in headers]
    col_list = ", ".join(select_items)
    order_clause = f"ORDER BY {_RN} DESC" if overrides.get("mutant_reverse_order") else f"ORDER BY {_RN}"
    sql = f"SELECT {col_list} FROM {t_q} {order_clause}"
    return (sql, list(headers))


def _map_extract_text_between_delimiters(
    step: dict[str, Any], headers: list[str], t_q: str, store: DuckStore | None, overrides: dict[str, Any]
) -> tuple[str, list[str]] | Refusal:
    column = step.get("column")
    start_delimiter = step.get("start_delimiter")
    end_delimiter = step.get("end_delimiter")
    start_occurrence = step.get("start_occurrence")
    end_occurrence = step.get("end_occurrence")
    # Engine order (`_validate_step`): column name (then stripped), start and end delimiters, the two occurrences.
    if not isinstance(column, str) or not column.strip():
        message = "Transformation step 1 needs a column name."
        return Refusal(message, expected_error="needs a column name.")
    if not isinstance(start_delimiter, str) or not start_delimiter:
        message = "Transformation step 1 needs a non-empty start delimiter."
        return Refusal(message, expected_error="needs a non-empty start delimiter.")
    if not isinstance(end_delimiter, str) or not end_delimiter:
        message = "Transformation step 1 needs a non-empty end delimiter."
        return Refusal(message, expected_error="needs a non-empty end delimiter.")
    if not isinstance(start_occurrence, int) or isinstance(start_occurrence, bool) or start_occurrence < 0 or start_occurrence > 100000:
        message = "Transformation step 1 needs start occurrence from 0 to 100,000."
        return Refusal(message, expected_error="needs start occurrence from 0 to 100,000.")
    if not isinstance(end_occurrence, int) or isinstance(end_occurrence, bool) or end_occurrence < 0 or end_occurrence > 100000:
        message = "Transformation step 1 needs end occurrence from 0 to 100,000."
        return Refusal(message, expected_error="needs end occurrence from 0 to 100,000.")
    column = column.strip()
    if column not in headers:
        message = f"Column {column!r} does not exist."
        return Refusal(message, expected_error=message)
    if store is None:
        return Refusal("DuckStore required to map extract_text_between_delimiters.")
    start_sql = sql_str(start_delimiter)
    end_sql = sql_str(end_delimiter)
    if isinstance(start_sql, Refusal):
        return start_sql
    if isinstance(end_sql, Refusal):
        return end_sql
    c = f'"{column}"'
    s_occ = start_occurrence
    e_occ = end_occurrence
    prefix_len = f"length(list_aggregate(list_slice(string_split({c}, {start_sql}), 1, {s_occ + 1}), 'string_agg', {start_sql}))"
    start_len = f"length({start_sql})"
    rem_expr = f"substr({c}, {prefix_len} + {start_len} + 1)"
    check_query = (
        f'SELECT {_RN}, '
        f'CASE '
        f'  WHEN {c} IS NOT NULL AND {c} != \'\' AND len(string_split({c}, {start_sql})) <= {s_occ + 1} THEN 1 '
        f'  WHEN {c} IS NOT NULL AND {c} != \'\' AND len(string_split({rem_expr}, {end_sql})) <= {e_occ + 1} THEN 2 '
        f'  ELSE 0 '
        f'END AS err_type '
        f'FROM {t_q} '
        f'WHERE {c} IS NOT NULL AND {c} != \'\' '
        f'ORDER BY {_RN}'
    )
    scanned = store.execute(check_query)
    for rn_idx, (rn_val, err_type) in enumerate(scanned, 1):
        if err_type == 1 and not overrides.get("mutant_missing_delimiter_returns_blank"):
            row_idx_rows = store.execute(
                f'SELECT rn FROM (SELECT {_RN}, (row_number() OVER (ORDER BY {_RN})) AS rn FROM {t_q}) WHERE {_RN} = {rn_val}'
            )
            row_idx = row_idx_rows[0][0] if row_idx_rows else rn_idx
            message = f"Could not find start delimiter occurrence {start_occurrence} in row {row_idx} of column {column!r}."
            return Refusal(message, expected_error=message)
        elif err_type == 2 and not overrides.get("mutant_missing_delimiter_returns_blank"):
            row_idx_rows = store.execute(
                f'SELECT rn FROM (SELECT {_RN}, (row_number() OVER (ORDER BY {_RN})) AS rn FROM {t_q}) WHERE {_RN} = {rn_val}'
            )
            row_idx = row_idx_rows[0][0] if row_idx_rows else rn_idx
            message = f"Could not find end delimiter occurrence {end_occurrence} after start delimiter occurrence {start_occurrence} in row {row_idx} of column {column!r}."
            return Refusal(message, expected_error=message)
    if overrides.get("mutant_between_delimiters_inclusive"):
        between_expr = f"({start_sql} || list_aggregate(list_slice(string_split({rem_expr}, {end_sql}), 1, {e_occ + 1}), 'string_agg', {end_sql}) || {end_sql})"
    else:
        between_expr = f"list_aggregate(list_slice(string_split({rem_expr}, {end_sql}), 1, {e_occ + 1}), 'string_agg', {end_sql})"
    final_expr = f"CASE WHEN {c} IS NULL THEN NULL WHEN {c} = '' THEN '' ELSE {between_expr} END"
    select_items = [f'{final_expr} AS "{h}"' if h == column else f'"{h}"' for h in headers]
    col_list = ", ".join(select_items)
    order_clause = f"ORDER BY {_RN} DESC" if overrides.get("mutant_reverse_order") else f"ORDER BY {_RN}"
    sql = f"SELECT {col_list} FROM {t_q} {order_clause}"
    return (sql, list(headers))


def _map_conditional_column(
    step: dict[str, Any],
    headers: list[str],
    t_q: str,
    overrides: dict[str, Any],
    col_meta: dict[str, dict[str, Any]] | None = None,
    total_rows: int = 0,
) -> tuple[str, list[str]] | Refusal:
    name = step.get("name")
    clauses = step.get("clauses")
    else_value = step.get("else_value")
    else_kind = step.get("else_kind")
    if not isinstance(name, str) or not name.strip():
        message = "Transformation step 1 needs a new column name."
        return Refusal(message, expected_error="needs a new column name.")
    name = name.strip()
    if not isinstance(clauses, list) or not clauses:
        message = "Transformation step 1 needs one or more conditional clauses."
        return Refusal(message, expected_error="needs one or more conditional clauses.")
    if len(clauses) > MAX_CONDITIONAL_CLAUSES:
        message = f"A conditional column may contain at most {MAX_CONDITIONAL_CLAUSES} clauses."
        return Refusal(message, expected_error="may contain at most")
    clause_fields = {"column", "operator", "test_value", "test_value_kind", "output", "output_kind"}
    for c_idx, cl in enumerate(clauses, 1):
        if not isinstance(cl, dict) or set(cl) != clause_fields or any(not isinstance(v, str) for v in cl.values()):
            message = f"Clause {c_idx} in step 1 has missing or invalid fields."
            return Refusal(message, expected_error="has missing or invalid fields.")
        c_col = cl["column"].strip()
        op = cl["operator"].strip()
        t_val = cl["test_value"]
        t_kind = cl["test_value_kind"].strip()
        out = cl["output"]
        o_kind = cl["output_kind"].strip()
        if not c_col:
            message = f"Clause {c_idx} in step 1 needs a test column."
            return Refusal(message, expected_error="needs a test column.")
        if op not in _CONDITIONAL_OPERATORS:
            message = f"Clause {c_idx} in step 1 has an unsupported operator."
            return Refusal(message, expected_error="has an unsupported operator.")
        if t_kind not in _CONDITIONAL_VALUE_KINDS:
            message = f"Clause {c_idx} in step 1 has an invalid comparison-value type."
            return Refusal(message, expected_error="has an invalid comparison-value type.")
        if t_kind == "column" and not t_val.strip():
            message = f"Clause {c_idx} in step 1 needs a comparison column."
            return Refusal(message, expected_error="needs a comparison column.")
        if t_kind == "null" and t_val:
            message = f"Clause {c_idx} in step 1 must use an empty placeholder for a null comparison."
            return Refusal(message, expected_error="must use an empty placeholder for a null comparison.")
        if o_kind not in {"value", "column"}:
            message = f"Clause {c_idx} in step 1 has an invalid output type."
            return Refusal(message, expected_error="has an invalid output type.")
        if o_kind == "column" and not out.strip():
            message = f"Clause {c_idx} in step 1 needs an output column."
            return Refusal(message, expected_error="needs an output column.")
    if not isinstance(else_value, str) or not isinstance(else_kind, str):
        message = "Transformation step 1 needs a valid final else value."
        return Refusal(message, expected_error="needs a valid final else value.")
    else_kind = else_kind.strip()
    if else_kind not in {"value", "column"}:
        message = "Transformation step 1 has an invalid final else type."
        return Refusal(message, expected_error="has an invalid final else type.")
    if else_kind == "column" and not else_value.strip():
        message = "Transformation step 1 needs a final else column."
        return Refusal(message, expected_error="needs a final else column.")
    if name in headers:
        message = f"Column {name!r} already exists."
        return Refusal(message, expected_error=message)
    if len(headers) >= MAX_COLUMNS:
        message = f"Adding a conditional column exceeds the {MAX_COLUMNS}-column limit."
        return Refusal(message, expected_error=message)
    if total_rows * (len(headers) + 1) > MAX_CELLS:
        message = f"Adding a conditional column exceeds the {MAX_CELLS:,}-cell limit."
        return Refusal(message, expected_error=message)
    required_cols: set[str] = set()
    for cl in clauses:
        required_cols.add(cl["column"].strip())
        if cl["test_value_kind"].strip() == "column":
            required_cols.add(cl["test_value"].strip())
        if cl["output_kind"].strip() == "column":
            required_cols.add(cl["output"].strip())
    if else_kind == "column":
        required_cols.add(else_value.strip())
    missing = sorted(required_cols - set(headers))
    if missing:
        message = f"Conditional column refers to missing column {missing[0]!r}."
        return Refusal(message, expected_error=message)
    unsafe = unsafe_header_reason(name)
    if unsafe:
        return Refusal(unsafe)
    case_branches = []
    active_clauses = list(reversed(clauses)) if overrides.get("mutant_conditional_last_clause_wins") else clauses
    for cl in active_clauses:
        c_col = cl["column"].strip()
        op = cl["operator"].strip()
        t_val = cl["test_value"].strip() if cl["test_value_kind"].strip() == "column" else cl["test_value"]
        t_kind = cl["test_value_kind"].strip()
        out = cl["output"].strip() if cl["output_kind"].strip() == "column" else cl["output"]
        o_kind = cl["output_kind"].strip()
        left_col = f'"{c_col}"'
        if t_kind == "column":
            right_val = f'"{t_val}"'
            is_col = True
        elif t_kind == "null":
            right_val = "NULL"
            is_col = False
        else:
            right_lit = sql_str(t_val)
            if isinstance(right_lit, Refusal):
                return right_lit
            right_val = right_lit
            is_col = False
        if op in {"equals", "not_equals"}:
            if t_kind == "null":
                cond = f'({left_col} IS NULL)' if op == "equals" else f'({left_col} IS NOT NULL)'
            elif is_col:
                # engine: equal only when both are NULL, or both present and equal; a NULL on one side is not equal
                eq_expr = (f'(({left_col} IS NOT NULL AND {right_val} IS NOT NULL AND {left_col} = {right_val}) '
                           f'OR ({left_col} IS NULL AND {right_val} IS NULL))')
                cond = eq_expr if op == "equals" else f'(NOT {eq_expr})'
            else:
                eq_expr = f'({left_col} IS NOT NULL AND {left_col} = {right_val})'
                cond = eq_expr if op == "equals" else f'(NOT {eq_expr})'
        elif op in {"contains", "does_not_contain"}:
            if t_kind == "null":
                cond = "FALSE" if op == "contains" else "TRUE"
            elif is_col:
                cnt_expr = f'({left_col} IS NOT NULL AND {right_val} IS NOT NULL AND position({right_val} in {left_col}) > 0)'
                cond = cnt_expr if op == "contains" else f'({left_col} IS NULL OR {right_val} IS NULL OR NOT {cnt_expr})'
            else:
                cnt_expr = f'({left_col} IS NOT NULL AND position({right_val} in {left_col}) > 0)'
                cond = cnt_expr if op == "contains" else f'({left_col} IS NULL OR NOT {cnt_expr})'
        elif op in {"begins_with", "does_not_begin_with"}:
            if t_kind == "null":
                cond = "FALSE" if op == "begins_with" else "TRUE"
            elif is_col:
                bg_expr = f'({left_col} IS NOT NULL AND {right_val} IS NOT NULL AND starts_with({left_col}, {right_val}))'
                cond = bg_expr if op == "begins_with" else f'({left_col} IS NULL OR {right_val} IS NULL OR NOT {bg_expr})'
            else:
                bg_expr = f'({left_col} IS NOT NULL AND starts_with({left_col}, {right_val}))'
                cond = bg_expr if op == "begins_with" else f'({left_col} IS NULL OR NOT {bg_expr})'
        elif op in {"ends_with", "does_not_end_with"}:
            if t_kind == "null":
                cond = "FALSE" if op == "ends_with" else "TRUE"
            elif is_col:
                ed_expr = f'({left_col} IS NOT NULL AND {right_val} IS NOT NULL AND ends_with({left_col}, {right_val}))'
                cond = ed_expr if op == "ends_with" else f'({left_col} IS NULL OR {right_val} IS NULL OR NOT {ed_expr})'
            else:
                ed_expr = f'({left_col} IS NOT NULL AND ends_with({left_col}, {right_val}))'
                cond = ed_expr if op == "ends_with" else f'({left_col} IS NULL OR NOT {ed_expr})'
        elif op in {"greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal"}:
            op_sym = {
                "greater_than": ">", "greater_than_or_equal": ">=",
                "less_than": "<", "less_than_or_equal": "<="
            }[op]
            if t_kind == "null":
                cond = "FALSE"
            else:
                # The engine (`_conditional_clause_matches`) compares Decimal values when both sides parse
                # (Decimal(text.strip())), else the texts. The SQL side uses the same expression as the filter
                # path (`sql_num_expr`), guarded by the column facts that filter_rows uses (`num_cast_agrees`:
                # the SQL value is NULL exactly where the engine does not parse, and exact where it does).
                # Whatever the facts cannot vouch for is refused by name, never compared as text.
                for fact_column in [c_col] + ([t_val] if is_col else []):
                    fact = (col_meta or {}).get(fact_column)
                    if fact is None:
                        return Refusal(f"No column facts for {fact_column!r}.")
                    if not fact.get("num_cast_agrees", True):
                        message = (
                            f"Column {fact_column!r} holds numeric text SQL does not read like the engine "
                            "(non-ASCII digits, a value of 10^20 or more, underscores in odd places, or more than 18 decimals)."
                        )
                        return Refusal(message)
                n_left = sql_num_expr(c_col)
                if is_col:
                    n_right = sql_num_expr(t_val)
                else:
                    num_lit = engine_number(t_val)
                    dec_lit = decimal_literal(num_lit) if num_lit is not None else None
                    if num_lit is not None and dec_lit is None:
                        return Refusal(
                            f"Clause {c_idx} in step 1 compares with {t_val!r}, outside the exact SQL decimal range."
                        )
                    n_right = f"CAST('{dec_lit}' AS {SQL_DECIMAL})" if dec_lit is not None else "NULL"
                cond = (
                    f'({left_col} IS NOT NULL AND ('
                    f'  CASE WHEN {n_left} IS NOT NULL AND {n_right} IS NOT NULL THEN ({n_left} {op_sym} {n_right}) '
                    f'  ELSE ({left_col} {op_sym} {right_val}) END'
                    f'))'
                )
        else:
            message = f"Unsupported conditional operator {op!r}."
            return Refusal(message, expected_error=message)
        if o_kind == "column":
            out_expr = f'"{out}"'
        else:
            out_lit = sql_str(out)
            if isinstance(out_lit, Refusal):
                return out_lit
            out_expr = out_lit
        case_branches.append(f"WHEN {cond} THEN {out_expr}")
    if overrides.get("mutant_conditional_else_ignored"):
        else_expr = "NULL"
    elif else_kind == "column":
        else_expr = f'"{else_value.strip()}"'
    else:
        else_lit = sql_str(else_value)
        if isinstance(else_lit, Refusal):
            return else_lit
        else_expr = else_lit
    case_sql = f"(CASE {' '.join(case_branches)} ELSE {else_expr} END)"
    out_headers = [*headers, name]
    col_list = ", ".join(f'"{h}"' for h in headers) + f', {case_sql} AS "{name}"'
    order_clause = f"ORDER BY {_RN} DESC" if overrides.get("mutant_reverse_order") else f"ORDER BY {_RN}"
    sql = f"SELECT {col_list} FROM {t_q} {order_clause}"
    return (sql, out_headers)


def _map_replace_error_values(
    step: dict[str, Any], headers: list[str], t_q: str
) -> tuple[str, list[str]] | Refusal:
    """replace_error_values: a CSV table holds no error cells, so a valid step is the identity.

    The engine checks every named column exists (first missing one, in order) and stops with its own text.
    """
    for pair in step["replacements"]:
        if pair[0] not in headers:
            message = f"Error replacement column {pair[0]!r} does not exist."
            return Refusal(message, expected_error=message)
    col_list = ", ".join(f'"{h}"' for h in headers)
    return (f"SELECT {col_list} FROM {t_q} ORDER BY {_RN}", list(headers))


# ---------------------------------------------------------------- D1b: convert_type (slice 5, Part A step 1)
# Engine: `_convert_column` -> `_convert_value` (per cell; a failed cell becomes a PowerQueryCellError whose
# str() is "Error: " + the engine message). Store side: the text of the converted cell, or the same error text.
CONVERT_STORE_TYPES = {"text", "any", "boolean", "whole_number", "decimal_number", "number", "date", "datetime", "time"}
CONVERT_ERROR_PREFIX = "Error: "
CONVERT_DIAG_CHARS = 120  # transformations.MAX_CONVERSION_DIAGNOSTIC_VALUE_CHARS
CONVERT_YEAR_RX = r"([1-9][0-9]{3}|0[1-9][0-9]{2}|00[1-9][0-9]|000[1-9])"  # years 0001..9999
# Strict forms the SQL mirrors (anything else non-blank is a named refusal: the engine's Python parser takes more).
CONVERT_DATE_PY = CONVERT_YEAR_RX + r"-[0-9]{2}-[0-9]{2}"
CONVERT_DATETIME_PY = CONVERT_DATE_PY + r"([ T][0-9]{2}:[0-9]{2}:[0-9]{2})?"
CONVERT_TIME_PY = r"([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
CONVERT_DATE_SQL = "^" + CONVERT_DATE_PY + "$"
CONVERT_DATETIME_SQL = "^" + CONVERT_DATETIME_PY + "$"
CONVERT_TIME_SQL = "^" + CONVERT_TIME_PY + "$"
CONVERT_DECIMAL_MIN_ADJUSTED = -6  # below this Decimal's str() switches to exponent form (1E-7)
CONVERT_DECIMAL_MAX_ADJUSTED = 300  # float(Decimal) overflows near 10**309 (the engine's finite check)


def _convert_plain_repr(text: str) -> bool:
    """The engine prints a value as repr(text) in its error message: only plain printable ASCII is mirrored."""
    return len(text) <= CONVERT_DIAG_CHARS and all(32 <= ord(ch) <= 126 and ch not in "'\\" for ch in text)


def _convert_column_facts(store: DuckStore, table_name: str, column: str) -> dict[str, Any]:
    """Facts about one column's cells that decide the convert_type mapping (read from the store, load order)."""
    values = [r[0] for r in store.execute(f'SELECT "{column}" FROM "{table_name}" ORDER BY {_RN}')]
    nonblank = [v for v in values if v not in (None, "")]
    numbers = [engine_number(v) for v in nonblank]
    nonzero = [n for n in numbers if n is not None and n != 0]
    return {
        "blank": any(v == "" for v in values),
        "repr_plain": _convert_plain_repr(column) and all(_convert_plain_repr(v) for v in nonblank),
        "ascii": all(v.isascii() for v in nonblank),
        "exponent": any("e" in v or "E" in v for v in nonblank),
        "error_prefix": any(v.startswith(CONVERT_ERROR_PREFIX) for v in nonblank),
        "date_strict": all(re.fullmatch(CONVERT_DATE_PY, v.strip()) for v in nonblank),
        "datetime_strict": all(re.fullmatch(CONVERT_DATETIME_PY, v.strip()) for v in nonblank),
        "time_strict": all(re.fullmatch(CONVERT_TIME_PY, v.strip()) for v in nonblank),
        "min_adjusted": min((n.adjusted() for n in nonzero), default=None),
        "max_adjusted": max((n.adjusted() for n in nonzero), default=None),
    }


def _convert_decimal_text_sql(n: str, overrides: dict[str, Any]) -> str:
    """str(Decimal(text)) for a plain number text n (sign, digits, optional fraction; no exponent).

    The engine's `_decimal_number_text` gives "0" or "-0" for every zero (signed zero keeps its sign), keeps the
    fraction digits exactly, and drops leading zeros of the integer part ("007.50" -> "7.50", ".5" -> "0.5", "1." -> "1").
    """
    sign = f"CASE WHEN left({n}, 1) = '-' THEN '-' ELSE '' END"
    body = f"ltrim({n}, '+-')"
    integer = f"split_part({body}, '.', 1)"
    fraction = f"split_part({body}, '.', 2)"
    if overrides.get("mutant_convert_keep_leading_zeros"):
        int_text = integer
    else:
        int_text = f"CASE WHEN ltrim({integer}, '0') = '' THEN '0' ELSE ltrim({integer}, '0') END"
    if overrides.get("mutant_convert_strip_fraction_zeros"):
        fraction = f"rtrim({fraction}, '0')"
    zero = f"(TRY_CAST({n} AS {SQL_DECIMAL}) = 0)"
    zero_text = "'0'" if overrides.get("mutant_convert_zero_unsigned") else f"{sign} || '0'"
    return (
        f"CASE WHEN {zero} THEN {zero_text} ELSE {sign} || {int_text} "
        f"|| CASE WHEN {fraction} <> '' THEN '.' || {fraction} ELSE '' END END"
    )


def _map_convert_type(
    step: dict[str, Any],
    headers: list[str],
    t_q: str,
    table_name: str,
    overrides: dict[str, Any],
    col_meta: dict[str, dict[str, Any]] | None,
    store: DuckStore | None,
) -> tuple[str, list[str]] | Refusal:
    """convert_type (`_convert_column`): one column to one of the engine's types; a failed cell is an error cell.

    Mapped: blank and unconvertible cells (error text, row number, the engine's repr of the value), text and any
    (identity), boolean (true/false in any case, padded), whole_number and decimal_number (plain numbers: padded,
    underscores, sign, leading zeros, "1.", ".5", "-0"; whole_number rounds half to even and checks the 64-bit range),
    date, datetime and time (strict ISO forms only). Refused by name: exponent text, non-ASCII text, a value the
    DECIMAL(38,18) cast holds inexactly, a decimal below 1E-6 or above 1E300, non-strict dates, earlier-step error text,
    and a value or column name the engine's repr prints differently (quote, backslash, non-ASCII, over 120 characters).
    """
    # The engine's order (`validate_steps`, then apply): every value must be text, the column name not blank,
    # the type supported; then the column must exist. (The field set was checked by `_d0h_shape_refusal`.)
    if any(not isinstance(value, str) for value in step.values()):
        message = "Transformation step 1 values must be strings."
        return Refusal(message, expected_error="values must be strings.")
    column = step.get("column")
    if not column.strip():
        message = "Transformation step 1 needs a column name."
        return Refusal(message, expected_error="needs a column name.")
    target = canonical_column_type(step.get("type"))
    if target not in CONVERT_STORE_TYPES:
        message = "Transformation step 1 has an unsupported column type."
        return Refusal(message, expected_error="has an unsupported column type.")
    if column not in headers:
        message = f"Column {column!r} does not exist."
        return Refusal(message, expected_error=message)
    if target in {"text", "any"}:
        col_list = ", ".join(f'"{h}"' for h in headers)
        return (f"SELECT {col_list} FROM {t_q} ORDER BY {_RN}", list(headers))
    if store is None or col_meta is None or column not in col_meta:
        return Refusal("convert_type needs the column facts of the store.")
    if "_cv_rn" in headers:
        return Refusal("A column named _cv_rn clashes with the row number used for the error text.")
    facts = _convert_column_facts(store, table_name, column)
    if facts["error_prefix"]:
        return Refusal("A cell holds text that starts with the engine's error prefix; the store cannot tell it from an error cell.")
    if not facts["repr_plain"]:
        return Refusal("A value or column name is not plain printable ASCII; the engine's error text quotes it differently.")
    ws = sql_str(PY_WHITESPACE)
    raw = f'"{column}"'
    s = raw if overrides.get("mutant_convert_no_trim") else f"trim({raw}, {ws})"
    if target == "boolean":
        if not facts["ascii"]:
            return Refusal("Boolean text with non-ASCII characters is not mirrored (Unicode case rules).")
        lowered = f"lower({s})" if not overrides.get("mutant_convert_bool_case_sensitive") else s
        ok = f"{lowered} IN ('true', 'false')"
        value = f"CASE WHEN {lowered} = 'true' THEN 'True' ELSE 'False' END"
    elif target in {"decimal_number", "whole_number"}:
        if not col_meta[column]["ascii_only"] or not facts["ascii"]:
            return Refusal("Number text with non-ASCII digits or spaces is not mirrored (the engine reads Unicode digits).")
        if facts["exponent"]:
            return Refusal("Exponent number text (1e3): the engine keeps the Decimal exponent form (1E+3); not mirrored.")
        if not col_meta[column]["num_cast_agrees"]:
            return Refusal("A value does not fit DECIMAL(38,18) exactly (engine precision); not mirrored.")
        n = s if overrides.get("mutant_convert_no_underscore") else f"replace({s}, '_', '')"
        number = f"TRY_CAST({n} AS {SQL_DECIMAL})"
        if target == "decimal_number":
            if facts["min_adjusted"] is not None and facts["min_adjusted"] < CONVERT_DECIMAL_MIN_ADJUSTED:
                return Refusal("A decimal below 1E-6 prints in exponent form (1E-7) in the engine; not mirrored.")
            if facts["max_adjusted"] is not None and facts["max_adjusted"] >= CONVERT_DECIMAL_MAX_ADJUSTED:
                return Refusal("A decimal of 300 or more integer digits overflows the engine's float check; not mirrored.")
            ok = f"{number} IS NOT NULL"
            value = _convert_decimal_text_sql(n, overrides)
        else:
            # round_even() returns DOUBLE for DECIMAL input (it loses 19-digit integers), so the half-to-even step
            # is written on DECIMAL: round() is half away from zero; at an exact .5 an odd result steps back to even.
            away = f"round({number}, 0)"
            if overrides.get("mutant_convert_whole_half_up"):
                rounded = away
            else:
                rounded = (
                    f"CASE WHEN abs({number} - trunc({number})) = 0.5 AND ({away}) % 2 <> 0 "
                    f"THEN ({away}) - sign({number}) ELSE ({away}) END"
                )
            big = f"CAST({rounded} AS VARCHAR)" if overrides.get("mutant_convert_whole_no_range") else f"CAST(TRY_CAST({rounded} AS BIGINT) AS VARCHAR)"
            ok = f"{big} IS NOT NULL"
            value = big
    elif target == "date":
        if not facts["date_strict"]:
            return Refusal("Dates other than yyyy-mm-dd: the engine also takes times, Z and compact forms; SQL differs.")
        ok = f"regexp_matches({s}, '{CONVERT_DATE_SQL}')"
        if not overrides.get("mutant_convert_date_no_validity"):
            ok += f" AND TRY_CAST({s} AS DATE) IS NOT NULL"
        value = f"CAST(TRY_CAST({s} AS DATE) AS VARCHAR)" if not overrides.get("mutant_convert_date_no_validity") else s
    elif target == "datetime":
        if not facts["datetime_strict"]:
            return Refusal("Datetimes other than yyyy-mm-dd[ T]hh:mm:ss: the engine takes minutes, offsets and fractions; SQL differs.")
        stamp = f"replace({s}, 'T', ' ')"
        ok = f"regexp_matches({s}, '{CONVERT_DATETIME_SQL}') AND TRY_CAST({stamp} AS TIMESTAMP) IS NOT NULL"
        value = f"strftime(TRY_CAST({stamp} AS TIMESTAMP), '%Y-%m-%d %H:%M:%S')"
    elif target == "time":
        if not facts["time_strict"]:
            return Refusal("Times other than hh:mm:ss (00 to 23): the engine takes 24:00:00, minutes-only and fractions; SQL differs.")
        ok = f"regexp_matches({s}, '{CONVERT_TIME_SQL}') AND TRY_CAST({s} AS TIME) IS NOT NULL"
        value = s
    else:
        return Refusal(f"convert_type to {target} is not mapped.")
    # The engine's message: Cannot convert value <repr> in row <n> of column <repr> to <type>.
    row_text = "CAST(_cv_rn AS VARCHAR)" if not overrides.get("mutant_convert_error_row_plus_one") else "CAST(_cv_rn + 1 AS VARCHAR)"
    if overrides.get("mutant_convert_error_column_unquoted"):
        message_parts = [
            sql_str(f"{CONVERT_ERROR_PREFIX}Cannot convert value '"), raw, sql_str("' in row "), row_text,
            sql_str(" of column "), sql_str(column), sql_str(f" to {target}."),
        ]
    else:
        message_parts = [
            sql_str(f"{CONVERT_ERROR_PREFIX}Cannot convert value '"), raw, sql_str("' in row "), row_text,
            sql_str(" of column '"), sql_str(column), sql_str(f"' to {target}."),
        ]
    err = " || ".join(f"CAST({p} AS VARCHAR)" if p == raw else p for p in message_parts)
    if overrides.get("mutant_convert_blank_is_null"):
        converted = f"CASE WHEN {raw} IS NULL OR {raw} = '' THEN NULL WHEN {ok} THEN {value} ELSE {err} END"
    else:
        converted = f"CASE WHEN {raw} IS NULL THEN NULL WHEN {ok} THEN {value} ELSE {err} END"
    out_list = ", ".join(
        f'{converted} AS "{h}"' if h == column else f'"{h}"' for h in headers
    )
    plain_list = ", ".join(f'"{h}"' for h in headers)
    inner = f"SELECT {plain_list}, ROW_NUMBER() OVER (ORDER BY {_RN}) AS _cv_rn FROM {t_q}"
    return (f"SELECT {out_list} FROM ({inner}) ORDER BY _cv_rn", list(headers))


# ---------------------------------------------------------------- D1b: convert_type_using_locale (Part A step 2)
# Engine: `_convert_column_using_locale` -> `_convert_value_using_locale`: Babel parse_decimal(strict=True) for
# en-US. Measured (brute force, 960,799 strings over 0 1 , . - + 5 up to 7 characters): the grammar below is the
# same as Babel's for en-US; the value and the error text are otherwise the convert_type ones plus " using culture en-US.".
# Only en-US (canonical) and decimal_number / whole_number are mapped; other cultures and types are named refusals.
LOCALE_EN_US_NUMBER_PY = r"-?[1-9][0-9]{0,2}(,[0-9]{3})+(\.[0-9]+)?|[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)"
LOCALE_EN_US_NUMBER_SQL = "^(" + LOCALE_EN_US_NUMBER_PY + ")$"
LOCALE_TYPES = {"whole_number", "decimal_number", "date", "datetime", "time"}


def _map_convert_type_using_locale(
    step: dict[str, Any],
    headers: list[str],
    t_q: str,
    table_name: str,
    overrides: dict[str, Any],
    col_meta: dict[str, dict[str, Any]] | None,
    store: DuckStore | None,
) -> tuple[str, list[str]] | Refusal:
    """convert_type_using_locale (en-US numbers only). The engine's order: values are text, the column name is not
    blank (the engine strips it), the type is a locale type, the culture is valid (canonicalised), then the column.
    """
    if any(not isinstance(value, str) for value in step.values()):
        message = "Transformation step 1 values must be strings."
        return Refusal(message, expected_error="values must be strings.")
    if not step["column"].strip():
        message = "Transformation step 1 needs a column name."
        return Refusal(message, expected_error="needs a column name.")
    if step["type"] not in LOCALE_TYPES:
        message = "Transformation step 1 has an unsupported locale-aware column type."
        return Refusal(message, expected_error="has an unsupported locale-aware column type.")
    try:
        culture = _canonical_culture(step["culture"])
    except TransformationError as exc:
        return Refusal(f"Transformation step 1: {exc}", expected_error="is not recognized.")
    column = step["column"].strip()
    if column not in headers:
        message = f"Column {column!r} does not exist."
        return Refusal(message, expected_error=message)
    if culture != "en-US":
        return Refusal(f"convert_type_using_locale with culture {culture} is not mapped (en-US only).")
    if step["type"] not in {"whole_number", "decimal_number"}:
        return Refusal(f"convert_type_using_locale to {step['type']} with en-US is not mapped (numbers only).")
    if store is None or col_meta is None or column not in col_meta or "_cv_rn" in headers:
        return Refusal("convert_type_using_locale needs the column facts of the store.")
    facts = _convert_column_facts(store, table_name, column)
    if facts["error_prefix"]:
        return Refusal("A cell holds text that starts with the engine's error prefix; the store cannot tell it from an error cell.")
    if not facts["repr_plain"]:
        return Refusal("A value or column name is not plain printable ASCII; the engine's error text quotes it differently.")
    if not facts["ascii"] or not col_meta[column]["ascii_only"]:
        return Refusal("Number text with non-ASCII characters is not mirrored (Babel reads other digits).")
    values = [r[0] for r in store.execute(f'SELECT "{column}" FROM "{table_name}" ORDER BY {_RN}')]
    nonblank = [v for v in values if v not in (None, "")]
    if any("e" in v or "E" in v or "_" in v for v in nonblank):
        return Refusal("Exponent or underscore number text: Babel reads it (1E+3, 1_000); the SQL grammar does not.")
    accepted = [Decimal(v.strip().replace(",", "")) for v in nonblank if re.fullmatch(LOCALE_EN_US_NUMBER_PY, v.strip())]
    if any(decimal_literal(number) is None for number in accepted):
        return Refusal("A value does not fit DECIMAL(38,18) exactly (engine precision); not mirrored.")
    nonzero = [n for n in accepted if n != 0]
    if nonzero and min(n.adjusted() for n in nonzero) < CONVERT_DECIMAL_MIN_ADJUSTED:
        return Refusal("A decimal below 1E-6 prints in exponent form (1E-7) in the engine; not mirrored.")
    if nonzero and max(n.adjusted() for n in nonzero) >= CONVERT_DECIMAL_MAX_ADJUSTED:
        return Refusal("A decimal of 300 or more integer digits overflows the engine's float check; not mirrored.")
    ws = sql_str(PY_WHITESPACE)
    raw = f'"{column}"'
    s = f"trim({raw}, {ws})"
    n = s if overrides.get("mutant_locale_keeps_commas") else f"replace({s}, ',', '')"
    number = f"TRY_CAST({n} AS {SQL_DECIMAL})"
    ok = f"regexp_matches({s}, '{LOCALE_EN_US_NUMBER_SQL}') AND {number} IS NOT NULL"
    if step["type"] == "decimal_number":
        value = _convert_decimal_text_sql(n, overrides)
    else:
        away = f"round({number}, 0)"
        rounded = away if overrides.get("mutant_convert_whole_half_up") else (
            f"CASE WHEN abs({number} - trunc({number})) = 0.5 AND ({away}) % 2 <> 0 "
            f"THEN ({away}) - sign({number}) ELSE ({away}) END"
        )
        value = f"CAST(TRY_CAST({rounded} AS BIGINT) AS VARCHAR)"
        ok = f"{ok} AND {value} IS NOT NULL"
    tail = f"' to {step['type']}." if overrides.get("mutant_locale_message_no_culture") else f"' to {step['type']} using culture {culture}."
    err_parts = [
        sql_str(f"{CONVERT_ERROR_PREFIX}Cannot convert value '"), raw, sql_str("' in row "),
        "CAST(_cv_rn AS VARCHAR)", sql_str(" of column '"), sql_str(column),
        sql_str(tail),
    ]
    err = " || ".join(f"CAST({p} AS VARCHAR)" if p == raw else p for p in err_parts)
    converted = f"CASE WHEN {raw} IS NULL THEN NULL WHEN {ok} THEN {value} ELSE {err} END"
    out_list = ", ".join(f'{converted} AS "{h}"' if h == column else f'"{h}"' for h in headers)
    plain_list = ", ".join(f'"{h}"' for h in headers)
    inner = f"SELECT {plain_list}, ROW_NUMBER() OVER (ORDER BY {_RN}) AS _cv_rn FROM {t_q}"
    return (f"SELECT {out_list} FROM ({inner}) ORDER BY _cv_rn", list(headers))


# ---------------------------------------------------------------- D1b: sparse rows and table pass-through (Part A steps 5, 6)
# Engine: `_is_sparse_boundary_row`: a row is sparse when it has at most one meaningful cell (a cell that is not None
# and not whitespace-only) and no error cell. `remove_sparse_top_rows` drops leading sparse rows, the bottom step
# trailing ones; an all-sparse table ends empty. Store side: the same count in SQL with window functions.
def _map_remove_sparse_rows(
    headers: list[str], t_q: str, table_name: str, top: bool, overrides: dict[str, Any], store: DuckStore | None
) -> tuple[str, list[str]] | Refusal:
    if store is None:
        return Refusal("A sparse-row step needs the store.")
    if "_sp_rn" in headers or "_sp_sparse" in headers or "_sp_first" in headers or "_sp_last" in headers:
        return Refusal("A column named _sp_* clashes with the sparse-row work columns.")
    plain_list = ", ".join(f'"{h}"' for h in headers)
    cells = store.execute(f"SELECT {plain_list} FROM {t_q}") if headers else []
    if any(isinstance(v, str) and v.startswith(CONVERT_ERROR_PREFIX) for row in cells for v in row):
        return Refusal("A cell holds text that starts with the engine's error prefix; the store cannot tell it from an error cell.")
    ws = sql_str(PY_WHITESPACE)
    meaningful = " + ".join(
        f'CASE WHEN "{h}" IS NOT NULL AND trim("{h}", {ws}) <> \'\' THEN 1 ELSE 0 END' for h in headers
    ) or "0"
    limit = 0 if overrides.get("mutant_sparse_at_most_zero") else 1
    inner = f"SELECT {plain_list}, ROW_NUMBER() OVER (ORDER BY {_RN}) AS _sp_rn, ({meaningful}) <= {limit} AS _sp_sparse FROM {t_q}"
    if top:
        mid = "MIN(CASE WHEN NOT _sp_sparse THEN _sp_rn END) OVER () AS _sp_first"
        keep = "_sp_first IS NOT NULL AND _sp_rn >= _sp_first" if not overrides.get("mutant_sparse_drops_first") else "_sp_first IS NOT NULL AND _sp_rn > _sp_first"
    else:
        mid = "MAX(CASE WHEN NOT _sp_sparse THEN _sp_rn END) OVER () AS _sp_last"
        keep = "_sp_last IS NOT NULL AND _sp_rn <= _sp_last"
    return (
        f"SELECT {plain_list} FROM (SELECT *, {mid} FROM ({inner})) WHERE {keep} ORDER BY _sp_rn",
        list(headers),
    )


def _map_table_pass_through(headers: list[str], t_q: str) -> tuple[str, list[str]]:
    """table_pass_through: the engine copies the step and changes nothing (no field check)."""
    plain_list = ", ".join(f'"{h}"' for h in headers)
    return (f"SELECT {plain_list} FROM {t_q} ORDER BY {_RN}", list(headers))


# ---------------------------------------------------------------- D1b/D1c: named refusals for three steps the store cannot run
NAMED_UNSUPPORTED_REASONS = {
    "add_custom_column": (
        "add_custom_column: the store does not evaluate the custom-column expression language (M expressions); "
        "not mirrored."
    ),
    "m_script": (
        "m_script: the store does not run M scripts (a whole M program); not mirrored."
    ),
    "m_sparse_boundary_helper": (
        "m_sparse_boundary_helper: the store does not bind the M helper that the sparse-row steps read; not mirrored."
    ),
}


def _map_named_unsupported(step: dict[str, Any]) -> Refusal:
    """One named refusal per step the engine accepts but the store does not run (a plain sentence each)."""
    return Refusal(NAMED_UNSUPPORTED_REASONS[step["op"]])


_TEXT_STEP_FIELDS = {"op", "column"}
D0H_STEP_FIELDS: dict[str, set[str]] = {
    "convert_type": {"op", "column", "type"},
    "convert_type_using_locale": {"op", "column", "type", "culture"},
    "remove_sparse_top_rows": {"op"},
    "remove_sparse_bottom_rows": {"op"},
    "add_custom_column": {"op", "name", "expression"},
    "m_sparse_boundary_helper": {"op", "name"},
    "m_script": {"op", "script", "source_binding"},
    "group_by": {"op", "columns", "aggregations"},
    "replace_value": {"op", "column", "value", "replacement"},
    "merge_columns": {"op", "columns", "separator", "new_name"},
    "split_column": {"op", "column", "delimiter"},
    "split_column_by_each_delimiter": {"op", "column", "delimiter"},
    "replace_error_values": {"op", "replacements"},
    **{name: _TEXT_STEP_FIELDS for name in (
        "trim_text", "clean_text", "lowercase_text", "uppercase_text", "proper_case_text", "reverse_text")},
    "promote_headers": {"op"},
    "demote_headers": {"op"},
    "transpose_table": {"op"},
    "unpivot_columns": {"op", "columns", "attribute_name", "value_name"},
    "unpivot_other_columns": {"op", "columns", "attribute_name", "value_name"},
    "split_column_to_rows": {"op", "column", "delimiter"},
    "split_column_by_positions": {"op", "column", "positions"},
    "extract_text_by_delimiter": {"op", "column", "delimiter", "side", "occurrence"},
    "extract_text_between_delimiters": {"op", "column", "start_delimiter", "end_delimiter", "start_occurrence", "end_occurrence"},
    "conditional_column": {"op", "name", "clauses", "else_value", "else_kind"},
}
D0H_OPTIONAL_STEP_FIELDS: dict[str, set[str]] = {
    "replace_value": {"replacer"},
    "split_column": {"from_end", "missing_part"},
    "split_column_by_each_delimiter": {"from_end", "missing_part"},
    "promote_headers": {"promote_all_scalars"},
    "add_custom_column": {"output_type"},
}


def _d0h_shape_refusal(step: dict[str, Any]) -> Refusal | None:
    """A D0h step with a missing or unknown field: the engine's text (checked before anything else), never a KeyError."""
    op = step.get("op")
    required = D0H_STEP_FIELDS.get(op)
    if required is None:
        return None
    if not required <= set(step) <= required | D0H_OPTIONAL_STEP_FIELDS.get(op, set()):
        return Refusal("The step has missing or unsupported fields.", expected_error="has missing or unsupported fields.")
    return None


def generate_sequence_sql(
    item: dict[str, Any],
    headers: list[str],
    table_name: str,
    total_rows: int,
    overrides: dict[str, Any] | None,
    col_meta: dict[str, dict[str, Any]] | None,
    store: DuckStore,
) -> tuple[str, list[str]] | Refusal | str:
    """SQL for a sequence item (`item["sequence"]`): each step runs on the previous step's output.

    The output of every step but the last is materialised as a derived store table with a fresh hidden row-order
    column `__rn`, numbered in that output's order (guess: DuckDB keeps the ORDER BY order of the step's SQL).
    The last step's SQL is returned for the usual comparison against the engine's whole-sequence result.
    """
    overrides = overrides or {}
    current_name, current_headers, current_total, current_meta = table_name, list(headers), total_rows, col_meta
    steps = item["sequence"]
    result: tuple[str, list[str]] | Refusal | str = Refusal("An empty step sequence cannot run.")
    for index, step in enumerate(steps):
        result = generate_step_sql(
            {"id": item["id"], "step": step}, current_headers, current_name, current_total,
            overrides=overrides, col_meta=current_meta, store=store,
        )
        if isinstance(result, Refusal) or index == len(steps) - 1:
            return result
        sql, out_headers = result
        derived = f"{item['id']}_step{index + 1}"
        try:
            out_rows = store.execute(sql)
            if store.has_table(derived):
                store.drop_table(derived)
            store.create_table(derived, [(h, "text") for h in out_headers])
            store.append_rows(derived, [list(r) for r in out_rows])
        except Exception as exc:
            return str(exc)
        current_name = derived
        current_headers = list(out_headers)
        current_total = store.execute(f'SELECT COUNT(*) FROM "{derived}"')[0][0]
        current_meta = inspect_store_columns(store, derived, current_headers)
    return result


def generate_step_sql(
    item: dict[str, Any],
    headers: list[str],
    table_name: str,
    total_rows: int,
    overrides: dict[str, Any] | None = None,
    col_meta: dict[str, dict[str, bool]] | None = None,
    store: DuckStore | None = None,
) -> tuple[str, list[str]] | Refusal:
    """Generate SQL query and expected output columns for a step item.

    Returns (sql_query, output_headers) or a Refusal object.
    `mutant_null_for_blank` (inert by default) wraps every selected column in
    NULLIF(col, '') so a blank cell comes back as NULL; the tool must flag it.
    """
    overrides = overrides or {}
    result = _mapped_sql(item, headers, table_name, total_rows, overrides, col_meta=col_meta, store=store)
    if isinstance(result, Refusal) or not overrides.get("mutant_null_for_blank"):
        return result
    sql, out_headers = result
    if overrides.get("forced_sql_syntax_error"):
        return result
    wrapped = ", ".join(f'NULLIF(CAST("{h}" AS VARCHAR), \'\') AS "{h}"' for h in out_headers)
    return (f"SELECT {wrapped} FROM ({sql})", out_headers)


def _mapped_sql(
    item: dict[str, Any],
    headers: list[str],
    table_name: str,
    total_rows: int,
    overrides: dict[str, Any],
    col_meta: dict[str, dict[str, bool]] | None = None,
    store: DuckStore | None = None,
) -> tuple[str, list[str]] | Refusal:
    """The SQL mapping of each step (see `generate_step_sql`)."""
    t_q = f'"{table_name}"'
    step = item["step"]
    op = step.get("op")

    if overrides.get("forced_sql_syntax_error"):
        return ("SELECT INVALID SYNTAX FROM " + t_q, headers)

    # 1. keep_columns
    if op == "keep_columns":
        cols = step["columns"]
        missing = [c for c in cols if c not in headers]
        if missing:
            return Refusal(
                f"Column {missing[0]!r} does not exist.",
                expected_error=f"Column {missing[0]!r} does not exist.",
            )
        # Power Query preserves original header order filtered by selected set
        selected_set = set(cols)
        out_headers = [h for h in headers if h in selected_set]
        col_list = ", ".join(f'"{c}"' for c in out_headers)
        order_clause = f"ORDER BY {_RN} DESC" if overrides.get("mutant_reverse_order") else f"ORDER BY {_RN}"
        return (f"SELECT {col_list} FROM {t_q} {order_clause}", out_headers)

    # 2. remove_column
    if op == "remove_column":
        col = step["column"]
        # The engine checks that the column exists before it checks for the last column.
        if col not in headers:
            return Refusal(
                f"Column {col!r} does not exist.",
                expected_error=f"Column {col!r} does not exist.",
            )
        if len(headers) == 1:
            return Refusal(
                "Cannot remove the last column from a table.",
                expected_error="Cannot remove the last column from a table.",
            )
        out_headers = [h for h in headers if h != col]
        col_list = ", ".join(f'"{c}"' for c in out_headers)
        order_clause = f"ORDER BY {_RN} DESC" if overrides.get("mutant_reverse_order") else f"ORDER BY {_RN}"
        return (f"SELECT {col_list} FROM {t_q} {order_clause}", out_headers)

    # 3. reorder_columns
    if op == "reorder_columns":
        cols = step["columns"]
        for c in cols:
            if c not in headers:
                return Refusal(
                    f"Column {c!r} does not exist.",
                    expected_error=f"Column {c!r} does not exist.",
                )
        # Apply Power Query partial reordering semantics
        selected_set = set(cols)
        slots = [idx for idx, h in enumerate(headers) if h in selected_set]
        out_headers = list(headers)
        for idx, c in zip(slots, cols):
            out_headers[idx] = c
        col_list = ", ".join(f'"{c}"' for c in out_headers)
        order_clause = f"ORDER BY {_RN} DESC" if overrides.get("mutant_reverse_order") else f"ORDER BY {_RN}"
        return (f"SELECT {col_list} FROM {t_q} {order_clause}", out_headers)

    # 4. rename_column
    if op == "rename_column":
        col = step["column"]
        new_name = step["new_name"].strip()
        if col not in headers:
            return Refusal(
                f"Column {col!r} does not exist.",
                expected_error=f"Column {col!r} does not exist.",
            )
        if new_name in headers and new_name != col:
            return Refusal(
                f"Column {new_name!r} already exists.",
                expected_error=f"Column {new_name!r} already exists.",
            )
        out_headers = [new_name if h == col else h for h in headers]
        select_items = [f'"{h}" AS "{new_name}"' if h == col else f'"{h}"' for h in headers]
        col_list = ", ".join(select_items)
        order_clause = f"ORDER BY {_RN} DESC" if overrides.get("mutant_reverse_order") else f"ORDER BY {_RN}"
        return (f"SELECT {col_list} FROM {t_q} {order_clause}", out_headers)

    # 5. duplicate_column
    if op == "duplicate_column":
        col = step["column"]
        new_name = step["new_name"].strip()
        if col not in headers:
            return Refusal(
                f"Column {col!r} does not exist.",
                expected_error=f"Column {col!r} does not exist.",
            )
        if new_name in headers:
            return Refusal(
                f"Cannot duplicate {col!r}: output column {new_name!r} already exists.",
                expected_error=f"Cannot duplicate {col!r}: output column {new_name!r} already exists.",
            )
        out_headers = [*headers, new_name]
        col_list = ", ".join(f'"{c}"' for c in headers) + f', "{col}" AS "{new_name}"'
        order_clause = f"ORDER BY {_RN} DESC" if overrides.get("mutant_reverse_order") else f"ORDER BY {_RN}"
        return (f"SELECT {col_list} FROM {t_q} {order_clause}", out_headers)

    # 6. keep_top_rows
    if op == "keep_top_rows":
        count = step["count"]
        if overrides.get("mutant_top_off_by_one"):
            count += 1
        col_list = ", ".join(f'"{c}"' for c in headers)
        order_clause = "" if overrides.get("mutant_no_order_by") else f"ORDER BY {_RN}"
        return (f"SELECT {col_list} FROM {t_q} {order_clause} LIMIT {count}", list(headers))

    # 7. remove_top_rows
    if op == "remove_top_rows":
        count = step["count"]
        col_list = ", ".join(f'"{c}"' for c in headers)
        order_clause = "" if overrides.get("mutant_no_order_by") else f"ORDER BY {_RN}"
        return (f"SELECT {col_list} FROM {t_q} {order_clause} OFFSET {count}", list(headers))

    # 8. keep_bottom_rows
    if op == "keep_bottom_rows":
        count = step["count"]
        offset = max(0, total_rows - count)
        col_list = ", ".join(f'"{c}"' for c in headers)
        order_clause = "" if overrides.get("mutant_no_order_by") else f"ORDER BY {_RN}"
        return (f"SELECT {col_list} FROM {t_q} {order_clause} OFFSET {offset} LIMIT {count}", list(headers))

    # 9. remove_bottom_rows
    if op == "remove_bottom_rows":
        count = step["count"]
        keep_count = max(0, total_rows - count)
        col_list = ", ".join(f'"{c}"' for c in headers)
        order_clause = "" if overrides.get("mutant_no_order_by") else f"ORDER BY {_RN}"
        return (f"SELECT {col_list} FROM {t_q} {order_clause} LIMIT {keep_count}", list(headers))

    # 10. keep_range_rows
    if op == "keep_range_rows":
        first_row = step["first_row"]
        count = step["count"]
        offset = max(0, first_row - 1)
        if overrides.get("mutant_range_start_off_by_one"):
            offset += 1
        if overrides.get("mutant_range_count_off_by_one"):
            count += 1
        col_list = ", ".join(f'"{c}"' for c in headers)
        order_clause = "" if overrides.get("mutant_no_order_by") else f"ORDER BY {_RN}"
        return (f"SELECT {col_list} FROM {t_q} {order_clause} OFFSET {offset} LIMIT {count}", list(headers))

    # 11. remove_alternate_rows
    if op == "remove_alternate_rows":
        first_to_remove = step["first_row_to_remove"]
        rem = step["remove_count"]
        kp = step["keep_count"]
        if overrides.get("mutant_alt_offset_wrong"):
            first_to_remove += 1
        window_order = f"ORDER BY {_RN} DESC" if overrides.get("mutant_window_order_desc") else f"ORDER BY {_RN}"

        col_list = ", ".join(f'"{c}"' for c in headers)
        if rem == 0:
            cond = "1=1"
        elif kp == 0:
            cond = f"_rn < {first_to_remove}"
        else:
            cycle = rem + kp
            cond = f"(_rn < {first_to_remove} OR ((_rn - {first_to_remove}) % {cycle}) >= {rem})"

        sql = (
            f"SELECT {col_list} FROM ("
            f"  SELECT {col_list}, CAST(row_number() OVER ({window_order}) AS BIGINT) AS _rn FROM {t_q}"
            f") WHERE {cond} ORDER BY _rn"
        )
        return (sql, list(headers))

    # 12. count_rows
    if op == "count_rows":
        return (f"SELECT COUNT(*) AS \"Count\" FROM {t_q}", ["Count"])

    # 13. add_index_column
    if op == "add_index_column":
        new_name = step["new_name"]
        start = step["start"]
        inc = step["increment"]
        col_list = ", ".join(f'"{c}"' for c in headers)
        if overrides.get("mutant_index_start_off_by_one"):
            start += 1
        if overrides.get("mutant_index_increment_one"):
            inc = 1
        window_order = f"ORDER BY {_RN} DESC" if overrides.get("mutant_window_order_desc") else f"ORDER BY {_RN}"
        idx_expr = f"{start} + (CAST(row_number() OVER ({window_order}) AS BIGINT) - 1) * {inc}"
        out_headers = [*headers, new_name]
        order_clause = f"ORDER BY {_RN} DESC" if overrides.get("mutant_reverse_order") else f"ORDER BY {_RN}"
        sql = f"SELECT {col_list}, {idx_expr} AS \"{new_name}\" FROM {t_q} {order_clause}"
        return (sql, out_headers)

    # 14. remove_blank_rows
    if op == "remove_blank_rows":
        col_list = ", ".join(f'"{c}"' for c in headers)
        if overrides.get("mutant_blank_counts_whitespace"):
            # Whitespace counts as blank (differing from Power Query semantics)
            non_blank_preds = [f"trim(COALESCE(\"{c}\", '')) != ''" for c in headers]
        else:
            non_blank_preds = [f"COALESCE(\"{c}\", '') != ''" for c in headers]
        where_clause = " OR ".join(non_blank_preds)
        order_clause = f"ORDER BY {_RN} DESC" if overrides.get("mutant_reverse_order") else f"ORDER BY {_RN}"
        return (f"SELECT {col_list} FROM {t_q} WHERE ({where_clause}) {order_clause}", list(headers))

    # 15. append
    if op == "append":
        second_tbl = item.get("second_table", f"{table_name}_2")
        col_list = ", ".join(f'"{c}"' for c in headers)
        order_clause = "ORDER BY _src, _rn"
        if overrides.get("mutant_append_order_rn_src"):
            order_clause = "ORDER BY _rn, _src"
        if overrides.get("mutant_append_order_src_only"):
            order_clause = "ORDER BY _src"
        second_cols = ", ".join(f'"{c}"' for c in reversed(headers)) if overrides.get("mutant_append_column_order") else col_list
        sql = (
            f"SELECT {col_list} FROM ("
            f"  SELECT {col_list}, 0 AS _src, {_RN} AS _rn FROM {t_q}"
            f"  UNION ALL"
            f"  SELECT {second_cols}, 1 AS _src, {_RN} AS _rn FROM \"{second_tbl}\""
            f") {order_clause}"
        )
        return (sql, list(headers))

    # Helper for sorting a single column
    def _build_sort_expr(col: str, direction: str) -> str | Refusal:
        m = (col_meta or {}).get(col, {})
        is_num = bool(m.get("is_num", False)) and not overrides.get("mutant_sort_numeric_as_text")
        if is_num and not m.get("num_sql_exact", True):
            return Refusal(
                f"Column '{col}' holds numeric text that SQL_DECIMAL does not represent exactly "
                f"(non-ASCII digits, more than 18 decimals, 20+ integer digits or a huge exponent)."
            )

        dir_sql = direction.upper()

        if overrides.get("mutant_sort_nulls_first"):
            null_clause = f'CASE WHEN "{col}" IS NULL OR "{col}" = \'\' THEN 0 ELSE 1 END ASC'
        else:
            null_clause = f'CASE WHEN "{col}" IS NULL OR "{col}" = \'\' THEN 1 ELSE 0 END ASC'

        if is_num:
            # The engine sorts by Decimal(value.strip()) when every non-blank cell parses.
            val_clause = f"{sql_num_expr(col)} {dir_sql}"
        elif overrides.get("mutant_sort_ignore_non_ascii"):
            # Mutant (name kept from the old refusal): text sorted case-folded instead of raw code points.
            val_clause = f'lower("{col}") {dir_sql}'
        else:
            # The engine sorts text raw (`_sort_rows(case_sensitive=True)`); DuckDB VARCHAR order is bytewise.
            val_clause = f'"{col}" {dir_sql}'

        return f"{null_clause}, {val_clause}"

    # 16. sort_rows
    if op == "sort_rows":
        col = step["column"]
        if col not in headers:
            return Refusal(
                f"Column {col!r} does not exist.",
                expected_error=f"Column {col!r} does not exist.",
            )
        direction = step["direction"]
        sort_expr = _build_sort_expr(col, direction)
        if isinstance(sort_expr, Refusal):
            return sort_expr
        col_list = ", ".join(f'"{c}"' for c in headers)
        if overrides.get("mutant_sort_no_rn_tiebreak"):
            rn_clause = ""
        else:
            rn_clause = f', {_RN} ASC' if not overrides.get("mutant_sort_reverse_ties") else f', {_RN} DESC'
        sql = f"SELECT {col_list} FROM {t_q} ORDER BY {sort_expr}{rn_clause}"
        return (sql, list(headers))

    # 17. sort_rows_by_columns
    if op == "sort_rows_by_columns":
        sorts = step["sorts"]
        sort_parts: list[str] = []
        for s in sorts:
            col = s["column"]
            if col not in headers:
                return Refusal(
                    f"Column {col!r} does not exist.",
                    expected_error=f"Column {col!r} does not exist.",
                )
            direction = s["direction"]
            sort_expr = _build_sort_expr(col, direction)
            if isinstance(sort_expr, Refusal):
                return sort_expr
            sort_parts.append(sort_expr)
        col_list = ", ".join(f'"{c}"' for c in headers)
        combined_sort = ", ".join(sort_parts)
        if overrides.get("mutant_sort_no_rn_tiebreak"):
            rn_clause = ""
        else:
            rn_clause = f', {_RN} ASC' if not overrides.get("mutant_sort_reverse_ties") else f', {_RN} DESC'
        sql = f"SELECT {col_list} FROM {t_q} ORDER BY {combined_sort}{rn_clause}"
        return (sql, list(headers))

    # 18. filter_rows
    known_ops = {
        "equals", "not_equals", "contains", "does_not_contain", "begins_with", "does_not_begin_with",
        "ends_with", "does_not_end_with", "is_blank", "is_not_blank", "is_null", "is_not_null",
        "greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal",
        "date_before", "date_after", "date_on_or_before", "date_on_or_after", "is_earliest", "is_latest",
    }
    no_value_ops = {"is_null", "is_not_null", "is_blank", "is_not_blank", "is_earliest", "is_latest"}
    numeric_ops = {"greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal"}
    date_ops = {"date_before", "date_after", "date_on_or_before", "date_on_or_after"}
    date_message = "needs a valid date (yyyy-mm-dd) or datetime value."

    def _validate_filter(operator: str, value: str, idx: int, advanced: bool) -> Refusal | None:
        """The engine's step validation, in the engine's order (phase 0)."""
        if operator not in known_ops:
            text = "has an unsupported operator." if advanced else "has an unsupported filter operator."
            return Refusal(f"Unsupported filter operator {operator!r}.", expected_error=text, rank=(0, idx, 0))
        if operator in no_value_ops and value:
            text = (
                "does not use a comparison value."
                if advanced else "does not use a comparison value for this filter."
            )
            return Refusal(f"Operator {operator!r} takes no comparison value.", expected_error=text, rank=(0, idx, 1))
        if operator in date_ops and engine_date(value) is None:
            return Refusal(f"Filter value {value!r} is not a valid date.", expected_error=date_message, rank=(0, idx, 2))
        return None

    def _date_target(col: str, operator: str, value: str, idx: int) -> str | Refusal:
        """Comparison for a date filter; engine kinds mixing naive and aware raise inside Python."""
        m = (col_meta or {}).get(col)
        if m is None:
            return Refusal(f"No column facts for {col!r}.")
        kinds: dict[str, int] = m.get("date_kind_first_row", {})
        parsed = engine_date(value)
        assert parsed is not None
        e_kind, e_dt = parsed
        others = [kinds[k] for k in kinds if k != e_kind]
        if others:
            message = _mixed_offset_message()
            return Refusal(message, expected_error=message, rank=(2, min(others), idx))
        if not kinds:
            return "FALSE"
        if e_kind == "aware":
            return Refusal(f"Column {col!r} and the value hold offset-aware datetimes; SQL does not mirror them.")
        if not m.get("date_sql_exact", True):
            return Refusal(f"Column {col!r} holds date forms outside the strict ISO form the SQL cast mirrors.")
        op_map = {"date_before": "<", "date_after": ">", "date_on_or_before": "<=", "date_on_or_after": ">="}
        if overrides.get("mutant_filter_op_off_by_one"):
            op_map = {"date_before": "<=", "date_after": ">=", "date_on_or_before": "<", "date_on_or_after": ">"}
        return f"({sql_dt_expr(col)} {op_map[operator]} TIMESTAMP '{e_dt.isoformat(sep=' ')}')"

    def _numeric_cond(col: str, operator: str, value: str, idx: int) -> str | Refusal:
        number = engine_number(value)
        if number is None:
            return Refusal(
                f"Filter value {value!r} is not a finite number.",
                expected_error="Expected a finite number.",
                rank=(1, idx, 1),
            )
        m = (col_meta or {}).get(col)
        if m is None:
            return Refusal(f"No column facts for {col!r}.")
        literal = decimal_literal(number)
        if literal is None:
            return Refusal(f"Filter value {value!r} is outside the exact SQL decimal range.", rank=(1, idx, 1))
        bad = m.get("first_bad_number")
        if bad is not None:
            message = f"Value {bad[1]!r} in row {bad[0]} of column {col!r} is not a valid number."
            return Refusal(message, expected_error=message, rank=(2, bad[0], idx))
        if not m.get("num_sql_exact", True):
            return Refusal(f"Column {col!r} holds numeric text SQL does not represent exactly.")
        op_map = {"greater_than": ">", "greater_than_or_equal": ">=", "less_than": "<", "less_than_or_equal": "<="}
        if overrides.get("mutant_filter_op_off_by_one"):
            op_map = {"greater_than": ">=", "greater_than_or_equal": ">", "less_than": "<=", "less_than_or_equal": "<"}
        return f"({sql_num_expr(col)} {op_map[operator]} CAST('{literal}' AS {SQL_DECIMAL}))"

    def _build_filter_condition(col: str, operator: str, expected: str, idx: int = 0, advanced: bool = False) -> str | Refusal:
        invalid = _validate_filter(operator, expected, idx, advanced)
        if invalid is not None:
            return invalid
        if col not in headers:
            return Refusal(
                f"Column {col!r} does not exist.",
                expected_error=f"Column {col!r} does not exist.",
                rank=(1, idx, 0),
            )
        if operator in numeric_ops:
            return _numeric_cond(col, operator, expected, idx)
        if operator in date_ops:
            return _date_target(col, operator, expected, idx)
        if operator in {"is_earliest", "is_latest"}:
            # Only reached from an advanced clause: the engine has no clause form of these operators.
            if total_rows == 0:
                return "FALSE"
            message = f"Unsupported filter operator {operator!r}."
            return Refusal(message, expected_error=message, rank=(2, 1, idx))

        # Text and equality operators
        lit = sql_str(expected)
        if isinstance(lit, Refusal):
            return lit
        if operator == "equals":
            if overrides.get("mutant_filter_trim_trailing_spaces"):
                return f'rtrim(COALESCE("{col}", \'\')) = {lit}'
            return f'"{col}" = {lit}'
        if operator == "not_equals":
            return f'("{col}" IS NULL OR "{col}" != {lit})'
        if operator == "is_null":
            return f'"{col}" IS NULL'
        if operator == "is_not_null":
            return f'"{col}" IS NOT NULL'
        if operator == "is_blank":
            return f'("{col}" IS NULL OR "{col}" = \'\')'
        if operator == "is_not_blank":
            return f'("{col}" IS NOT NULL AND "{col}" != \'\')'
        if operator == "contains":
            return f'instr(COALESCE("{col}", \'\'), {lit}) > 0'
        if operator == "does_not_contain":
            return f'instr(COALESCE("{col}", \'\'), {lit}) = 0'
        if operator == "begins_with":
            return f'starts_with(COALESCE("{col}", \'\'), {lit})'
        if operator == "does_not_begin_with":
            return f'NOT starts_with(COALESCE("{col}", \'\'), {lit})'
        if operator == "ends_with":
            return f'ends_with(COALESCE("{col}", \'\'), {lit})'
        if operator == "does_not_end_with":
            return f'NOT ends_with(COALESCE("{col}", \'\'), {lit})'

        return Refusal(f"Unsupported filter operator {operator!r}")

    if op == "filter_rows":
        col = step["column"]
        operator = step["operator"]
        expected = step.get("value", "")
        col_list = ", ".join(f'"{c}"' for c in headers)
        order_clause = f"ORDER BY {_RN} DESC" if overrides.get("mutant_reverse_order") else f"ORDER BY {_RN}"
        if operator in {"is_earliest", "is_latest"}:
            invalid = _validate_filter(operator, expected, 0, False)
            if invalid is not None:
                return invalid
            if col not in headers:
                return Refusal(
                    f"Column {col!r} does not exist.",
                    expected_error=f"Column {col!r} does not exist.",
                )
            m = (col_meta or {}).get(col)
            if m is None:
                return Refusal(f"No column facts for {col!r}.")
            kinds = m.get("date_kind_first_row", {})
            if len(kinds) > 1:
                message = _mixed_offset_message()
                return Refusal(message, expected_error=message)
            if "aware" in kinds:
                return Refusal(f"Column {col!r} holds offset-aware datetimes; SQL does not mirror them.")
            if not m.get("date_sql_exact", True):
                return Refusal(f"Column {col!r} holds date forms outside the strict ISO form the SQL cast mirrors.")
            func = "MIN" if operator == "is_earliest" else "MAX"
            dt_sql = sql_dt_expr(col)
            sql = (
                f"WITH _dstats AS ("
                f"  SELECT {func}({dt_sql}) AS _target_dt "
                f"  FROM {t_q} "
                f"  WHERE {dt_sql} IS NOT NULL"
                f") "
                f"SELECT {col_list} FROM {t_q}, _dstats "
                f"WHERE {dt_sql} = _dstats._target_dt "
                f"{order_clause}"
            )
            return (sql, list(headers))

        cond = _build_filter_condition(col, operator, expected)
        if isinstance(cond, Refusal):
            return cond
        sql = f"SELECT {col_list} FROM {t_q} WHERE {cond} {order_clause}"
        return (sql, list(headers))

    # 19. filter_rows_advanced
    if op == "filter_rows_advanced":
        clauses = step["clauses"]
        or_groups: list[list[str]] = []
        curr_and_group: list[str] = []
        failures: list[Refusal] = []
        for c_idx, cl in enumerate(clauses):
            c_col = cl["column"]
            c_op = cl["operator"]
            c_val = cl.get("value", "")
            c_join = cl.get("join", "and")
            c_cond = _build_filter_condition(c_col, c_op, c_val, idx=c_idx, advanced=True)
            if isinstance(c_cond, Refusal):
                failures.append(c_cond)
                continue
            if c_idx == 0 or c_join == "and":
                curr_and_group.append(c_cond)
            else:
                or_groups.append(curr_and_group)
                curr_and_group = [c_cond]
        if failures:
            # The engine raises the first error it meets (validation, then preparation, then the row scan).
            engine_failures = [f for f in failures if f.expected_error]
            if engine_failures:
                return min(engine_failures, key=lambda f: f.rank)
            return failures[0]
        or_groups.append(curr_and_group)

        group_sqls = ["(" + " AND ".join(grp) + ")" for grp in or_groups if grp]
        where_sql = " OR ".join(group_sqls)
        col_list = ", ".join(f'"{c}"' for c in headers)
        order_clause = f"ORDER BY {_RN} DESC" if overrides.get("mutant_reverse_order") else f"ORDER BY {_RN}"
        sql = f"SELECT {col_list} FROM {t_q} WHERE ({where_sql}) {order_clause}"
        return (sql, list(headers))

    # 20. remove_duplicates
    if op == "remove_duplicates":
        cols = step.get("columns", headers)
        for c in cols:
            if c not in headers:
                return Refusal(
                    f"Column {c!r} does not exist.",
                    expected_error=f"Column {c!r} does not exist.",
                )
        if overrides.get("mutant_duplicate_casefold"):
            part_exprs = [f'("{c}" IS NULL), lower("{c}")' for c in cols]
        else:
            part_exprs = [f'("{c}" IS NULL), "{c}"' for c in cols]
        part_clause = ", ".join(part_exprs)
        col_list = ", ".join(f'"{c}"' for c in headers)
        sql = (
            f"SELECT {col_list} FROM ("
            f"  SELECT {col_list}, "
            f"         row_number() OVER (PARTITION BY {part_clause} ORDER BY {_RN}) AS _dup_rn, "
            f"         {_RN} "
            f"  FROM {t_q}"
            f") WHERE _dup_rn = 1 ORDER BY {_RN}"
        )
        return (sql, list(headers))

    # 21. keep_duplicates
    if op == "keep_duplicates":
        cols = step.get("columns", headers)
        for c in cols:
            if c not in headers:
                return Refusal(
                    f"Column {c!r} does not exist.",
                    expected_error=f"Column {c!r} does not exist.",
                )
        if overrides.get("mutant_duplicate_casefold"):
            part_exprs = [f'("{c}" IS NULL), lower("{c}")' for c in cols]
        else:
            part_exprs = [f'("{c}" IS NULL), "{c}"' for c in cols]
        part_clause = ", ".join(part_exprs)
        col_list = ", ".join(f'"{c}"' for c in headers)
        sql = (
            f"SELECT {col_list} FROM ("
            f"  SELECT {col_list}, "
            f"         count(*) OVER (PARTITION BY {part_clause}) AS _dup_cnt, "
            f"         {_RN} "
            f"  FROM {t_q}"
            f") WHERE _dup_cnt > 1 ORDER BY {_RN}"
        )
        return (sql, list(headers))

    # 22. fill_down & fill_up
    if op in {"fill_down", "fill_up"}:
        cols = step["columns"]
        for c in cols:
            if c not in headers:
                return Refusal(
                    f"Column {c!r} does not exist.",
                    expected_error=f"Column {c!r} does not exist.",
                )
        fill_set = set(cols)
        c_exprs: list[str] = []
        for h in headers:
            if h in fill_set:
                if overrides.get("mutant_fill_across_whitespace"):
                    # Blank defined by trim(c) != '' so whitespace cell is overwritten
                    non_null_expr = f'CASE WHEN "{h}" IS NOT NULL AND trim("{h}") != \'\' THEN "{h}" END'
                else:
                    non_null_expr = f'CASE WHEN "{h}" IS NOT NULL THEN "{h}" END'

                if op == "fill_down":
                    c_exprs.append(
                        f'COALESCE(last_value({non_null_expr} IGNORE NULLS) '
                        f'OVER (ORDER BY {_RN} ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW), "{h}") AS "{h}"'
                    )
                else:
                    c_exprs.append(
                        f'COALESCE(first_value({non_null_expr} IGNORE NULLS) '
                        f'OVER (ORDER BY {_RN} ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING), "{h}") AS "{h}"'
                    )
            else:
                c_exprs.append(f'"{h}"')
        col_list = ", ".join(c_exprs)
        sql = f"SELECT {col_list} FROM {t_q} ORDER BY {_RN}"
        return (sql, list(headers))

    # D0h steps
    shape = _d0h_shape_refusal(step)
    if shape is not None:
        return shape
    if op == "group_by":
        return _map_group_by(step, headers, t_q, table_name, total_rows, overrides, col_meta, store)
    if op == "replace_value":
        return _map_replace_value(step, headers, t_q, overrides)
    if op in {"trim_text", "clean_text", "lowercase_text", "uppercase_text", "proper_case_text", "reverse_text"}:
        return _map_text_transform(step, headers, t_q, overrides, col_meta)
    if op == "merge_columns":
        return _map_merge_columns(step, headers, t_q, overrides)
    if op in {"split_column", "split_column_by_each_delimiter"}:
        return _map_split_column(step, headers, t_q, table_name, overrides, store)
    if op == "replace_error_values":
        return _map_replace_error_values(step, headers, t_q)

    # D1b steps
    if op == "convert_type":
        return _map_convert_type(step, headers, t_q, table_name, overrides, col_meta, store)
    if op == "convert_type_using_locale":
        return _map_convert_type_using_locale(step, headers, t_q, table_name, overrides, col_meta, store)
    if op in {"remove_sparse_top_rows", "remove_sparse_bottom_rows"}:
        if set(step) != {"op"}:
            return Refusal("The step has missing or unsupported fields.", expected_error="has missing or unsupported fields.")
        return _map_remove_sparse_rows(headers, t_q, table_name, op == "remove_sparse_top_rows", overrides, store)
    if op == "table_pass_through":
        return _map_table_pass_through(headers, t_q)
    if op in NAMED_UNSUPPORTED_REASONS:
        return _map_named_unsupported(step)

    # D1a steps
    if op == "promote_headers":
        return _map_promote_headers(step, headers, t_q, store, overrides)
    if op == "demote_headers":
        return _map_demote_headers(step, headers, t_q, overrides)
    if op == "transpose_table":
        return _map_transpose_table(step, headers, t_q, total_rows, overrides)
    if op in {"unpivot_columns", "unpivot_other_columns"}:
        return _map_unpivot_columns(step, headers, t_q, unpivot_other=(op == "unpivot_other_columns"), overrides=overrides)
    if op == "split_column_to_rows":
        return _map_split_column_to_rows(step, headers, t_q, overrides)
    if op == "split_column_by_positions":
        return _map_split_column_by_positions(step, headers, t_q, overrides, total_rows)
    if op == "extract_text_by_delimiter":
        return _map_extract_text_by_delimiter(step, headers, t_q, store, overrides)
    if op == "extract_text_between_delimiters":
        return _map_extract_text_between_delimiters(step, headers, t_q, store, overrides)
    if op == "conditional_column":
        return _map_conditional_column(step, headers, t_q, overrides, col_meta, total_rows)

    return Refusal(f"Unknown or unsupported step operation: {op}")


def execute_engine_step(
    item: dict[str, Any],
    candidate: ImportCandidate,
    candidate_2: ImportCandidate | None = None,
) -> tuple[list[str], list[list[str | None]]] | str:
    """Execute step on row-by-row step engine.

    Returns (headers, rows_as_text_matrix) or error message string.
    """
    step = item["step"]
    op = step.get("op")

    try:
        if op == "append":
            if candidate_2 is None:
                raise TransformationError("Append requires two tables.")
            result = append_candidates([candidate, candidate_2])
        else:
            cand_input = candidate
            if item.get("single_column_context") and len(candidate.headers) > 1:
                # Candidate with only 1 column
                single_header = candidate.headers[0]
                cand_input = ImportCandidate(
                    kind=candidate.kind,
                    headers=[single_header],
                    rows=[{single_header: r[single_header]} for r in candidate.rows],
                    options=candidate.options,
                    notices=candidate.notices,
                )
            if item.get("sequence"):
                steps = list(item["sequence"])
            else:
                steps = [item["pre_step"], step] if item.get("pre_step") else [step]
            result = apply_transformations(cand_input, steps)

        out_headers = list(result.headers)
        out_rows: list[list[str | None]] = []
        for r in result.rows:
            row_vals = [normalize_cell(r.get(h)) for h in out_headers]
            out_rows.append(row_vals)
        return (out_headers, out_rows)
    except Exception as exc:
        return str(exc)


def execute_store_step(
    sql_or_refusal: tuple[str, list[str]] | Refusal,
    store: DuckStore,
) -> tuple[list[str], list[list[str | None]]] | Refusal | str:
    """Execute generated SQL against DuckStore.

    Returns (headers, rows_as_text_matrix), Refusal, or error message string.
    The headers come from the cursor description of the executed query, not from
    the generator's declared list (the declared list is only used for refusals).
    """
    if isinstance(sql_or_refusal, Refusal):
        return sql_or_refusal
    if isinstance(sql_or_refusal, str):
        return sql_or_refusal  # an SQL error met while a sequence materialised its earlier steps

    sql, _declared_headers = sql_or_refusal
    try:
        # Public guard path only: execute() is SELECT-only; DESCRIBE is wrapped in a SELECT.
        headers = [str(r[0]) for r in store.execute(f"SELECT column_name FROM (DESCRIBE {sql})")]
        records = store.execute(sql)
        out_rows: list[list[str | None]] = []
        for rec in records:
            row_vals = [normalize_cell(val) for val in rec]
            out_rows.append(row_vals)
        return (headers, out_rows)
    except Exception as exc:
        return str(exc)


def run_pq_step_diff(
    rows: int = 2000,
    seed: int = 42,
    overrides: dict[str, Any] | None = None,
    item_filter: list[str] | None = None,
    dataset: dict[str, Any] | None = None,
    items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """One differential run (see `run_pq_step_diff_many`)."""
    return run_pq_step_diff_many(rows, seed, [overrides or {}], item_filter, dataset, items)[0]


def run_pq_step_diff_many(
    rows: int,
    seed: int,
    override_sets: list[dict[str, Any]],
    item_filter: list[str] | None = None,
    dataset: dict[str, Any] | None = None,
    items: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Run differential comparison between step engine and DuckStore SQL.

    `dataset` (optional, for small hand-checked tables) is
    {"headers": [...], "rows": [[...]], "rows_2": [[...]]}: it replaces the generated
    CSV files; `rows_2` is the second table for append (default: the first table reversed).
    `items` (optional) replaces the step catalog with explicit step items.
    `override_sets`: one result per set of mutation switches; the data, the store and the engine result of
    every step are made once and shared (the engine never sees a switch), only the SQL side is run per set.
    """
    t_start = time.time()

    temp_dir = tempfile.mkdtemp(prefix="pq_store_diff_")
    t_path = Path(temp_dir)

    try:
        csv_file = t_path / "t.csv"
        csv_file_2 = t_path / "t2.csv"
        db_file = t_path / "store.db"

        if dataset is None:
            generate_pq_dataset(csv_file, rows=rows, seed=seed, include_blank_rows=True)
            generate_pq_dataset(csv_file_2, rows=min(rows, 100), seed=seed + 1, include_blank_rows=True)
        else:
            rows = len(dataset["rows"])
            rows_2 = dataset.get("rows_2", list(reversed(dataset["rows"])))
            for path, body in ((csv_file, dataset["rows"]), (csv_file_2, rows_2)):
                with open(path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(dataset["headers"])
                    writer.writerows(body)

        cand = parse_file(csv_file)
        cand_2 = parse_file(csv_file_2)
        headers = list(cand.headers)

        store = DuckStore(str(db_file))
        import_csv_to_store(store, "t_csv", csv_file, {})
        # Test seam (dataset "nulls": [[row index, column], ...]): a NULL cell, which a CSV cannot hold.
        # The engine side and the store side get the same NULL, so the comparison stays exact.
        null_cells = (dataset or {}).get("nulls", [])
        if null_cells:
            for row_index, null_column in null_cells:
                cand.rows[row_index][null_column] = None
            store.drop_table("t_csv")
            store.create_table("t_csv", [(h, "text") for h in headers])
            store.append_rows("t_csv", [[row[h] for h in headers] for row in cand.rows])
        import_csv_to_store(store, "t_csv_2", csv_file_2, {})

        total_store_rows = store.execute('SELECT COUNT(*) FROM "t_csv"')[0][0]
        col_meta = inspect_store_columns(store, "t_csv", headers)
        # Per item: (engine candidate, second candidate, headers, store table, row count, column meta).
        # "main" is the generated table; the D1a tables are small fixed tables (see `generate_d1a_csv`).
        table_ctx: dict[str, tuple[Any, Any, list[str], str, int, dict[str, dict[str, bool]]]] = {
            "main": (cand, cand_2, headers, "t_csv", total_store_rows, col_meta),
        }
        # Only the small tables the catalog names are generated and imported (same tables, same draws).
        catalog = list(items) if items is not None else build_step_catalog(headers, d1a=dataset is None)
        if item_filter:
            catalog = [item for item in catalog if item["id"] in set(item_filter)]
        needed_tables = {item.get("table", "main") for item in catalog}
        for shape in D1A_SHAPES + D1B_SHAPES:
            if shape not in needed_tables:
                continue
            d1a_path = t_path / f"{shape}.csv"
            if shape in D1B_SHAPES:
                generate_d1b_csv(d1a_path, seed, shape)
            else:
                generate_d1a_csv(d1a_path, seed, shape)
            import_csv_to_store(store, f"t_{shape}", d1a_path, {})
            d1a_cand = parse_file(d1a_path)
            d1a_headers = list(d1a_cand.headers)
            d1a_rows = store.execute(f'SELECT COUNT(*) FROM "t_{shape}"')[0][0]
            table_ctx[shape] = (
                d1a_cand, None, d1a_headers, f"t_{shape}", d1a_rows,
                inspect_store_columns(store, f"t_{shape}", d1a_headers),
            )

        results_sets: list[list[dict[str, Any]]] = [[] for _ in override_sets]

        for item in catalog:
            i_id = item["id"]
            step_op = item["step"]["op"]

            # 1. Reference side: step engine (on the item's own table)
            t_cand, t_cand_2, t_headers, t_name, t_total, t_meta = table_ctx[item.get("table", "main")]
            engine_res = execute_engine_step(item, t_cand, t_cand_2)

            for set_index, overrides in enumerate(override_sets):
                # 2. SQL side: store
                # The 'remove the last column' item runs on a one-column table: the engine side is
                # cropped to one column, so the SQL side sees the same one-column header list and
                # refuses because of that, not because of a flag.
                sql_headers = t_headers
                if item.get("single_column_context"):
                    sql_headers = t_headers[:1]
                elif item.get("pre_step"):
                    kept = set(item["pre_step"]["columns"])
                    sql_headers = [h for h in t_headers if h in kept]
                unsafe_reasons = [r for r in (unsafe_header_reason(h) for h in sql_headers) if r]
                if unsafe_reasons:
                    sql_or_ref = Refusal(unsafe_reasons[0])
                else:
                    if item.get("sequence"):
                        sql_or_ref = generate_sequence_sql(item, sql_headers, t_name, t_total, overrides, t_meta, store)
                    else:
                        sql_or_ref = generate_step_sql(item, sql_headers, t_name, t_total, overrides=overrides, col_meta=t_meta, store=store)
                store_res = execute_store_step(sql_or_ref, store)

                # 3. Compare
                diff_reason = ""
                diff_class = None
                status = "same"
                refusal_obj: Refusal | None = None

                if isinstance(store_res, Refusal):
                    refusal_obj = store_res
                    if isinstance(engine_res, str):
                        # Engine failed
                        if refusal_matches_engine_error(refusal_obj, engine_res):
                            status = "same"
                        else:
                            status = "refusal-reason-mismatch"
                            diff_reason = f"Refusal reason mismatch: expected {refusal_obj.expected_error!r} vs engine {engine_res!r}"
                    elif refusal_obj.expected_error:
                        # The tool expected the engine to raise this error, but the engine ran the step
                        status = "refusal-reason-mismatch"
                        diff_reason = f"Refusal expected engine error {refusal_obj.expected_error!r} but the engine succeeded"
                    else:
                        # SQL refused an operation where the engine succeeded (a named limit of the mapping)
                        status = "refused"
                        diff_reason = f"SQL refused step: {refusal_obj.reason}"
                elif isinstance(store_res, str):
                    # SQL execution threw an error
                    status = "sql-error"
                    diff_reason = f"SQL execution error: {store_res}"
                elif isinstance(engine_res, str):
                    # Engine threw an error but SQL did not refuse
                    status = "differs"
                    diff_reason = f"Engine raised error but SQL succeeded: {engine_res}"
                else:
                    # Both succeeded with (headers, rows)
                    eng_headers, eng_rows = engine_res
                    sql_headers, sql_rows = store_res

                    if overrides.get("forced_wrong_value") and i_id == catalog[0]["id"]:
                        eng_rows = [["forced_diff_val"]]

                    if step_op == "group_by" and eng_headers == sql_headers:
                        eng_rows, sql_rows = canonicalize_group_by_rows(item["step"], eng_rows, sql_rows)

                    if eng_headers != sql_headers:
                        status = "differs"
                        diff_reason = f"Header mismatch: engine={eng_headers} vs sql={sql_headers}"
                    elif len(eng_rows) != len(sql_rows):
                        status = "differs"
                        diff_reason = f"Row count mismatch: engine={len(eng_rows)} vs sql={len(sql_rows)}"
                    else:
                        mismatch_sample = None
                        for r_idx, (e_row, s_row) in enumerate(zip(eng_rows, sql_rows)):
                            if e_row != s_row:
                                mismatch_sample = (r_idx, e_row, s_row)
                                break
                        if mismatch_sample is not None:
                            status = "differs"
                            r_idx, e_row, s_row = mismatch_sample
                            diff_reason = f"Row {r_idx} mismatch: engine={e_row[:3]} vs sql={s_row[:3]}"

                if status == "differs" and overrides.get("forced_diff_class"):
                    diff_class = overrides["forced_diff_class"]

                results_sets[set_index].append({
                    "id": i_id,
                    "step_op": step_op,
                    "status": status,
                    "diff_reason": diff_reason,
                    "diff_class": diff_class,
                    "refusal": str(refusal_obj) if refusal_obj else None,
                    "refusal_reason": refusal_obj.reason if refusal_obj else None,
                    **({"table": item["table"], "d1a": True} if item.get("d1a") else {}),
                    **({"table": item["table"], "d1b": True} if item.get("d1b") else {}),
                })


        wall_sec = round(time.time() - t_start, 3)
        return [
            {
                "version": 1,
                "rows": rows,
                "seed": seed,
                "wall_sec": wall_sec,
                "total_steps": len(catalog),
                "results": results,
            }
            for results in results_sets
        ]
    finally:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)


def evaluate_exit_policy(data: dict[str, Any], baseline: dict[str, Any]) -> tuple[int, list[str]]:
    """Exit policy: returns (exit code, failure messages).

    Exit 1 on:
      - Any sql-error
      - Any refusal-reason-mismatch
      - Any difference outside a named class in baseline
      - Any refusal not in the baseline refused list (if refused list provided)
    """
    results = data["results"]
    messages: list[str] = []

    sql_errors = [r for r in results if r["status"] == "sql-error"]
    if sql_errors:
        messages.append(f"FAILURE: {len(sql_errors)} SQL errors encountered: {[r['id'] for r in sql_errors]}")

    refusal_mismatches = [r for r in results if r["status"] == "refusal-reason-mismatch"]
    if refusal_mismatches:
        messages.append(f"FAILURE: {len(refusal_mismatches)} refusal reason mismatches: {[r['id'] for r in refusal_mismatches]}")

    expected_classes = set(baseline.get("classes", []))
    unclassified_diffs = [
        r["id"] for r in results
        if r["status"] == "differs" and r.get("diff_class") not in expected_classes
    ]
    if unclassified_diffs:
        messages.append(f"FAILURE: {len(unclassified_diffs)} unclassified differences: {unclassified_diffs}")

    expected_refusals = baseline.get("refused")
    if expected_refusals is not None:
        actual_refusals = {r["id"] for r in results if r.get("refusal")}
        if actual_refusals != set(expected_refusals):
            diff_set = actual_refusals.symmetric_difference(set(expected_refusals))
            messages.append(f"FAILURE: Refused step set changed vs baseline: {diff_set}")

    exit_code = 1 if messages else 0
    return exit_code, messages


def generate_markdown_report(data: dict[str, Any]) -> str:
    """Generate markdown summary report."""
    results = data["results"]
    total = len(results)
    same_cnt = sum(1 for r in results if r["status"] == "same")
    diff_cnt = sum(1 for r in results if r["status"] == "differs")
    ref_cnt = sum(1 for r in results if r["status"] == "refused" or r.get("refusal"))
    sql_err_cnt = sum(1 for r in results if r["status"] == "sql-error")
    ref_mismatch_cnt = sum(1 for r in results if r["status"] == "refusal-reason-mismatch")

    lines = [
        "# Power Query Step Differential Report (Stage D0a)",
        "",
        f"- **Rows:** {data['rows']:,}",
        f"- **Seed:** {data['seed']}",
        f"- **Execution Time:** {data['wall_sec']} s",
        f"- **Total Step Tests:** {total}",
        f"- **Same:** {same_cnt}",
        f"- **Differs:** {diff_cnt}",
        f"- **Refusals:** {ref_cnt}",
        f"- **SQL Errors:** {sql_err_cnt}",
        f"- **Refusal Reason Mismatches:** {ref_mismatch_cnt}",
        "",
        "## Counts by Step Operation",
        "",
        "| Operation | Total | Same | Differs | Refused |",
        "|---|---|---|---|---|",
    ]

    by_op: dict[str, dict[str, int]] = {}
    for r in results:
        op = r["step_op"]
        if op not in by_op:
            by_op[op] = {"total": 0, "same": 0, "differs": 0, "refused": 0}
        by_op[op]["total"] += 1
        if r["status"] == "same":
            by_op[op]["same"] += 1
        elif r["status"] == "differs":
            by_op[op]["differs"] += 1
        if r.get("refusal"):
            by_op[op]["refused"] += 1

    for op in sorted(by_op):
        st = by_op[op]
        lines.append(f"| `{op}` | {st['total']} | {st['same']} | {st['differs']} | {st['refused']} |")

    lines.extend([
        "",
        "## Power BI Answer Checks Needed",
        "",
        "Rules chosen where Power Query behavior must be checked against Power BI Desktop:",
        "1. `remove_blank_rows`: In Power Query, whitespace-only cells (spaces, tabs) are NOT considered blank (only NULL and empty string `''`). The SQL mapping uses `COALESCE(col, '') != ''` to preserve whitespace-only rows.",
        "2. `append`: In this slice, tables share identical ordered columns. In Power BI, appending tables with disparate or mismatched schemas unions columns by name; disparate schemas are deferred to Tier 2/3.",
        "3. `keep_range_rows` / `remove_top_rows`: When offset or count exceeds total table row count, Power Query yields an empty table without error. The SQL mapping uses `OFFSET` / `LIMIT` matching this behavior.",
        "4. `remove_alternate_rows`: Alternating row selection cycle logic is mapped to modular arithmetic over `row_number()`. Power Query 1-based indexing semantics verified against step engine.",
        "5. Does Power Query keep an all-blank CSV row (`,,`) as a row of nulls? The app's CSV loader (engine parser and store import) drops all-blank rows at load, so remove_blank_rows on an imported CSV is the identity.",
        "6. `sort_rows` on mixed columns: The engine sorts numerically (by Decimal of the stripped text, so ' 5 ' and '1_000' count as numbers) only if every non-empty cell parses as a number; otherwise it sorts text in raw code point order. Power BI Desktop behaviour on mixed columns needs checking.",
        "7. `sort_rows` on text: the engine does NOT casefold (`_sort_rows(case_sensitive=True)`); the SQL matches raw order on sigma forms, sharp s, dotted I, accents, astral and CJK letters. Power BI sorts text with its own culture rules, which needs checking.",
        "8. `filter_rows` on dates: Dates parsed via ISO strings; Power BI culture-specific date parsing needs verification.",
        "9. Duplicate keys on numeric text: `cell_key` treats distinct string representations ('1' vs '1.0') distinctly for un-converted text columns, but equal if converted to Decimal.",
        "10. `fill_down` / `fill_up` whitespace: Whitespace-only cells are treated as non-blank and not overwritten.",
        "11. Date text '2026/06/15' and '20260615' (the engine uses Python date parsing: the first is not a date, the second is 2026-06-15): what does Power BI do with each?",
        "12. A date filter value with a time part ('2026-06-15 12:00:00') against a date-only column: the engine compares the cell date at midnight; what does Power BI return?",
        "13. Sorting numbers padded with spaces (' 5 ') as numbers or as text.",
        "14. Sorting numbers above 2^53 (9007199254740993 versus 9007199254740992): exact order.",
        "15. Trailing-space equality: 'cat ' versus 'cat' (the engine treats them as different; does Power BI?).",
        "16. `group_by` key equality: the engine groups on exact text ('a', 'A', 'a ', '', ' ', '1' and '1.0' are separate groups; a blank key is its own group, in first-seen order). Does Power BI Group By do the same with these keys?",
        "17. `group_by` sum, average, median over text numbers (' 4 ', '1_000', '1e2', '+3', '-0', '007'): the engine reads them with Decimal of the stripped text and averages at 28 digits. Does Power BI read them the same after its type step, and which digits does it keep?",
        "18. `group_by` min and max: all-numeric groups compare by value (first of equal values, '7' before '07'); other groups compare by Python casefold of the text. Does Power BI do the same for text, and what does it return for a group of blanks?",
        "19. `replace_value`: the default form replaces only a WHOLE cell that equals the target (case-sensitive, no trimming); the text form replaces every occurrence left to right without overlap (aa in aaa gives Xa). Check both, and a null replacement.",
        "20. Text transforms on Unicode: `lowercase_text`, `uppercase_text`, `proper_case_text` follow Python (final sigma, sharp s to SS, dotted I); `trim_text` strips every Python whitespace character; `clean_text` removes the control characters U+0000-001F and U+007F-009F; `reverse_text` reverses code points (a combining mark moves). Check each on those characters.",
        "21. `split_column_by_each_delimiter`: the width is the longest cell (at least two); short and blank cells give nulls (a blank cell is one empty part); a delimiter at an end or two in a row give empty parts; `split_column` with `from_end` splits at the LAST delimiter scanning from the right.",
        "22. `merge_columns`: a blank or null cell contributes empty text and the separator stays. Does Power BI Merge Columns keep the separator for a blank?",
        "",
        "## Deferred Steps (Slice 2+)",
        "",
        "Covered in slice 3 (D0h): `group_by`, `replace_value`, `replace_error_values`, `trim_text`, `clean_text`, `lowercase_text`, `uppercase_text`, `proper_case_text`, `reverse_text`, `merge_columns`, `split_column`, `split_column_by_each_delimiter`.",
        "Named refusals inside those steps: `lowercase_text`, `uppercase_text`, `proper_case_text` on a non-ASCII column; `group_by` min and max of non-numeric non-ASCII text; `group_by` average and median when the engine's precision rule needs more than 28 digits; numbers SQL does not read exactly; typed (bool, float) replacements.",
        "Covered in slice 4 (D1a): `promote_headers`, `demote_headers`, `transpose_table`, `unpivot_columns`, `unpivot_other_columns`, `split_column_to_rows`, `split_column_by_positions`, `extract_text_by_delimiter`, `extract_text_between_delimiters`, `conditional_column`.",
        "D1a catalog: 119 items (114 single steps and 5 sequences, each sequence runs on the previous step's output) on five generated D1a tables (a header-like first row, delimiter-bearing text, positional and unicode text, numeric edge values, and the empty, one-row, one-column and all-blank shapes), plus the refusal rules of each engine step by name.",
        "Power BI answers still to check (the engine's rule is the reference until a Power BI answer is saved): promote (duplicate names, blank, numeric and true/false headers, over-length names); transpose (headers dropped, Column1..N names, types); unpivot (row order, and null versus '' cells: Power BI drops null cells while the engine keeps '' as a row); split to rows (blank and null cells); split by positions (characters or UTF-16 units); extract (the engine raises an error on a missing delimiter while Power BI Text.BeforeDelimiter returns null); conditional (text versus number comparison, null, case, first match).",
        "The following operations in `transformations.py` remain deferred:",
        "- Type conversions: `convert_type`, `convert_type_using_locale`",
        "- Reshaping: `pivot_column`",
        "- Header / Table structure: `table_pass_through`",
        "- Scripting & Custom: `m_script`, `add_custom_column`, `m_sparse_boundary_helper`",
        "- Error handling: `remove_rows_with_errors`, `keep_rows_with_errors`",
        "- Sparse row removal: `remove_sparse_top_rows`, `remove_sparse_bottom_rows`",
        "",
    ])

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Power Query step differential tool.")
    parser.add_argument("--rows", type=int, default=2000, help="Row count for generated data (default: 2000)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    parser.add_argument("--out", type=str, default="", help="Output markdown file path")
    parser.add_argument("--json", type=str, default="", help="Output JSON file path")
    parser.add_argument("--baseline", type=str, default="", help="Path to baseline JSON file")

    args = parser.parse_args()

    try:
        data = run_pq_step_diff(rows=args.rows, seed=args.seed)
    except Exception as exc:
        print(f"TOOL CRASH: {exc}", file=sys.stderr)
        sys.exit(2)

    md_content = generate_markdown_report(data)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(md_content)
    else:
        print(md_content)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

    baseline_path = Path(args.baseline) if args.baseline else Path(__file__).parent / "pq_store_diff_baseline.json"
    try:
        with open(baseline_path, "r", encoding="utf-8") as bf:
            baseline_data = json.load(bf)
    except (OSError, ValueError) as exc:
        print(f"FAILURE: Error reading baseline {baseline_path.name}: {exc}", file=sys.stderr)
        sys.exit(1)

    code, messages = evaluate_exit_policy(data, baseline_data)
    for message in messages:
        print(message, file=sys.stderr)
    sys.exit(code)


if __name__ == "__main__":
    main()
