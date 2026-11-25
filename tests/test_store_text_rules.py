"""Tests for the shared text rules module (Stage C1pre).

Differential: generated strings are loaded into a DuckDB table; the SQL result must equal the Python reference
(fold_text, trim_text) and the real old path (_model_candidate_with_format_errors_as_blank). Mutants change one
rule of the SQL side; the differential must then fail by behaviour.
"""

from __future__ import annotations

import random

import duckdb
import pytest

from analytics_studio.controller import _model_candidate_with_format_errors_as_blank
from analytics_studio.file_import import ImportCandidate
from analytics_studio.store import text_rules
from analytics_studio.store.text_rules import fold_text, trim_text


# Characters that look like blanks or letters but are NOT trimmed and NOT folded by the model-load rule.
_EDGE_CHARS = [
    "\u0085", "\u00a0", "\u2028", "\u2029", "\u200b", "\u3000", "\ufeff", "\u00ad", "\u180e", "\u2003",
    "\uff21", "\uff41", "\u0130", "\u0131", "\u212a", "\u017f", "\u1e9e", "\u03a3", "\u03c2", "\u00c5", "\u212b",
    "\U0001f600", "\U0001f1e6\U0001f1ea", "\u0600", "\u200d", "\u0301", "\x7f", "\x80", "\x9f",
]
EDGE_VALUES: list[str | None] = []
for _char in _EDGE_CHARS:
    EDGE_VALUES += [_char, "x" + _char, "x" + _char + " ", "X" + _char + "\t", _char + _char + "\x00", "A" + _char + "\x00 "]
EDGE_VALUES += [
    "a" * 100000 + " ", "A" * 100000 + "\x00" * 50000, ("\u00e9" * 50000).upper() + " ", "x\x00y\x00",
    "\x00" * 5000, "A\x00B", "\U0001f600 ",
    "\uff21\uff41 ", "\uff21", "\uff41",
]


def _generated_values() -> list[str | None]:
    rng = random.Random(7)
    bases = [
        "Alpha", "ALPHA", "alpha", "aLpHa", "Beta Gamma", "beta gamma", "BETA GAMMA", "x", "X", "Zz9",
        "café", "CAFÉ", "Straße", "STRASSE", "İstanbul", "istanbul", "Ωmega", "ωmega", "ΩMEGA", "a b  c",
    ]
    controls = [chr(i) for i in range(33)]
    values: list[str | None] = ["", None, "\x00", "\x1f", " ", "\t\r\n", "".join(controls), " leading", "\tleading",
                                "  Inner  Space  ", "A\x00B", "a\x00b \x00", "Tab\t", "Tab ", "TAB\x01\x02"]
    values += bases
    for base in bases:
        for tail in (" ", "  ", "\t", "\x00", "\x1f", "\x1f ", "\x20\x00\x09", "!"):
            values.append(base + tail)
    for _ in range(300):
        base = rng.choice(bases)
        base = "".join(ch.upper() if rng.random() < 0.5 else ch.lower() for ch in base)
        values.append(rng.choice(["", " ", "\t"]) + base + "".join(rng.choice(controls) for _ in range(rng.randint(0, 4))))
    values += EDGE_VALUES
    rng.shuffle(values)
    return values


VALUES = _generated_values()


def _load(values: list[str | None]) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("CREATE TABLE t (v VARCHAR)")
    con.executemany("INSERT INTO t VALUES (?)", [(value,) for value in values])
    return con


def _python_first_spellings(values: list[str | None]) -> list[tuple[str, str]]:
    spellings: dict[str, str] = {}
    for value in values:
        spellings.setdefault(fold_text(value), trim_text(value))
    return list(spellings.items())


def _old_path_values(values: list[str | None]) -> list[str | None]:
    candidate = ImportCandidate(kind="csv", headers=["v"], rows=[{"v": value} for value in values],
                                options={"name": "t"}, notices=[])
    return [row["v"] for row in _model_candidate_with_format_errors_as_blank(candidate).rows]


def run_differential(values: list[str | None]) -> None:
    """Assert that SQL (read from the module at call time), the Python reference and the old path agree."""
    con = _load(values)
    sql_fold = [row[0] for row in con.execute(f"SELECT {text_rules.fold_sql('v')} FROM t ORDER BY rowid").fetchall()]
    sql_trim = [row[0] for row in con.execute(f"SELECT {text_rules.trim_sql('v')} FROM t ORDER BY rowid").fetchall()]
    assert sql_trim == [trim_text(value) for value in values]
    assert sql_fold == [fold_text(value) for value in values]
    sql_spellings = con.execute(text_rules.first_spelling_sql("t", "v")).fetchall()
    assert [tuple(row) for row in sql_spellings] == _python_first_spellings(values)
    spelling_of = dict(_python_first_spellings(values))
    old = _old_path_values(values)
    for value, old_value in zip(values, old):
        if value is None:
            assert old_value is None
        else:
            assert old_value == spelling_of[fold_text(value)]


def test_sql_matches_python_reference_and_old_path() -> None:
    run_differential(VALUES)


def test_known_cases_by_hand() -> None:
    # (value, folded, trimmed)
    cases = [
        ("Ab \t", "ab", "Ab"),
        ("AB", "ab", "AB"),
        ("\x00\x01\x1f ", "", ""),
        (" Lead", " lead", " Lead"),
        ("A B", "a b", "A B"),
        ("ÉßİΩ", "ÉßİΩ", "ÉßİΩ"),
        ("", "", ""),
        ("Z\x00", "z", "Z"),
        ("A\x00B", "a\x00b", "A\x00B"),
        ("x\x21", "x!", "x!"),
    ]
    con = _load([case[0] for case in cases])
    sql_fold = [row[0] for row in con.execute(f"SELECT {text_rules.fold_sql('v')} FROM t ORDER BY rowid").fetchall()]
    sql_trim = [row[0] for row in con.execute(f"SELECT {text_rules.trim_sql('v')} FROM t ORDER BY rowid").fetchall()]
    for (value, folded, trimmed), got_fold, got_trim in zip(cases, sql_fold, sql_trim):
        assert fold_text(value) == got_fold == folded
        assert trim_text(value) == got_trim == trimmed
    assert fold_text(None) == "" and trim_text(None) == ""
    con = _load(["Ab \t", "AB", "ab", "\x00\x01\x1f ", "ÉßİΩ", None])
    rows = [tuple(row) for row in con.execute(text_rules.first_spelling_sql("t", "v")).fetchall()]
    assert rows == [("ab", "Ab"), ("", ""), ("ÉßİΩ", "ÉßİΩ")]


def test_first_spelling_ordered_by_first_appearance() -> None:
    values = ["zeta", "ALPHA", "Zeta", "alpha", "Beta"]
    con = _load(values)
    rows = [tuple(row) for row in con.execute(text_rules.first_spelling_sql("t", "v")).fetchall()]
    assert rows == [("zeta", "zeta"), ("alpha", "ALPHA"), ("beta", "Beta")]


# Mutants: each breaks one rule on the SQL side only; the differential must then fail.

def test_mutant_fold_only_a_to_m(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(text_rules, "_UPPER", "ABCDEFGHIJKLM")
    monkeypatch.setattr(text_rules, "_LOWER", "abcdefghijklm")
    with pytest.raises(AssertionError):
        run_differential(VALUES)


def test_mutant_trim_stops_at_u001f(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(text_rules, "TRIM_CHARS_SQL", " || ".join(f"chr({i})" for i in range(32)))
    with pytest.raises(AssertionError):
        run_differential(VALUES)


def test_mutant_trim_also_strips_leading(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        text_rules, "trim_sql", lambda expr: f"trim(COALESCE({expr}, ''), {text_rules.TRIM_CHARS_SQL})"
    )
    with pytest.raises(AssertionError):
        run_differential(VALUES)


def test_mutant_fold_folds_non_ascii(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(text_rules, "fold_sql", lambda expr: f"lower({text_rules.trim_sql(expr)})")
    with pytest.raises(AssertionError):
        run_differential(VALUES)


def test_mutant_first_spelling_picks_last_seen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(text_rules, "first_spelling_expr_sql",
                        lambda expr, rowid="rowid": f"arg_max({text_rules.trim_sql(expr)}, {rowid})")
    with pytest.raises(AssertionError):
        run_differential(VALUES)


def test_mutant_trim_also_strips_unicode_blanks(monkeypatch: pytest.MonkeyPatch) -> None:
    extra = "".join(chr(code) for code in (0x00A0, 0x0085, 0x2028, 0x200B))

    def trim_mutant(expr: str) -> str:
        return f"rtrim(COALESCE({expr}, ''), {text_rules.TRIM_CHARS_SQL} || '{extra}')"

    monkeypatch.setattr(text_rules, "trim_sql", trim_mutant)
    with pytest.raises(AssertionError):
        run_differential(VALUES)


def test_mutant_consistent_unicode_blank_trim_in_sql_and_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    # Both SQL and the Python reference strip the extra characters: only the edge cases and the old path catch it.
    extra = "".join(chr(code) for code in (0x00A0, 0x0085, 0x2028, 0x200B))
    monkeypatch.setattr(text_rules, "TRIM_CHARS_SQL", text_rules.TRIM_CHARS_SQL + f" || '{extra}'")
    monkeypatch.setattr(text_rules, "_TRIM_CHARS", text_rules._TRIM_CHARS + extra)
    with pytest.raises(AssertionError):
        run_differential(VALUES)


def test_mutant_consistent_fullwidth_fold_in_sql_and_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(text_rules, "_UPPER", text_rules._UPPER + "\uff21")
    monkeypatch.setattr(text_rules, "_LOWER", text_rules._LOWER + "\uff41")
    monkeypatch.setattr(text_rules, "_ASCII_FOLD", str.maketrans(text_rules._UPPER, text_rules._LOWER))
    with pytest.raises(AssertionError):
        run_differential(VALUES)


def test_edge_characters_are_not_trimmed_or_folded() -> None:
    for char in ("\u0085", "\u00a0", "\u2028", "\u2029", "\u200b", "\u3000", "\ufeff", "\u00ad"):
        assert trim_text("x" + char) == "x" + char
    assert fold_text("\uff21") == "\uff21"
    assert fold_text("\U0001f600 ") == "\U0001f600"


def test_first_spelling_default_is_physical_rowid_and_rn_overrides() -> None:
    con = duckdb.connect()
    con.execute("CREATE TABLE d (v VARCHAR, __rn INTEGER)")
    con.executemany("INSERT INTO d VALUES (?, ?)", [("aB", 2), ("Ab", 1)])
    default_rows = [tuple(row) for row in con.execute(text_rules.first_spelling_sql("d", "v")).fetchall()]
    rn_rows = [tuple(row) for row in con.execute(text_rules.first_spelling_sql("d", "v", rowid="__rn")).fetchall()]
    assert default_rows == [("ab", "aB")]
    assert rn_rows == [("ab", "Ab")]
