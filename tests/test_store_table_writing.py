"""The change token of an append (Stage C4b fix 2): the token goes up before the COMMIT and after it, and the table is
flagged as "being written" from just before the COMMIT until both bumps are done, so a reader that compares tokens
around several statements can refuse rows that landed between two of them. No test asserts on elapsed time."""

from __future__ import annotations

from typing import Any

import pytest

from analytics_studio.store import DuckStore, StoreError


@pytest.fixture()
def store(tmp_path: Any) -> Any:
    with DuckStore(str(tmp_path / "w.duckdb")) as opened:
        opened.create_table("t", [("a", "text")])
        opened.append_rows("t", [("x",)])
        yield opened


def test_an_append_bumps_the_token_once_before_the_commit_and_once_after(store: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    original = DuckStore._bump_version
    seen: list[tuple[bool, bool]] = []  # (transaction still open, table flagged as being written) at each bump

    def spy(self: Any, name: str) -> None:
        seen.append((self._txn_open, self.table_writing(name)))
        original(self, name)

    monkeypatch.setattr(DuckStore, "_bump_version", spy)
    before = store.table_version("t")
    assert store.append_rows("t", [("y",), ("z",)]) == 2
    assert seen == [(True, True), (False, True)], seen  # first before the commit, second after it; both while flagged
    assert store.table_version("t") == before + 2
    assert store.table_writing("t") is False


def test_the_flag_is_per_table_ascii_case_insensitive_and_false_for_a_non_name(store: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    store.create_table("u", [("a", "text")])
    original = DuckStore._bump_version
    seen: list[tuple[bool, bool, bool, bool]] = []

    def spy(self: Any, name: str) -> None:
        seen.append((self.table_writing("t"), self.table_writing("T"), self.table_writing("u"), self.table_writing(None)))  # type: ignore[arg-type]
        original(self, name)

    monkeypatch.setattr(DuckStore, "_bump_version", spy)
    store.append_rows("t", [("y",)])
    assert seen[0] == (True, True, False, False), seen


def test_a_failed_append_leaves_the_token_and_the_flag_alone(store: Any) -> None:
    before = store.table_version("t")
    with pytest.raises(StoreError):
        store.append_rows("t", [("a", "too many")])
    assert store.table_version("t") == before and store.table_writing("t") is False


def test_a_failure_at_the_commit_clears_the_flag_and_rolls_back(store: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    # the first bump (just before the COMMIT) raises: the flag must not stay set and the rows must not be kept
    def boom(self: Any, name: str) -> None:
        raise RuntimeError("no bump")

    monkeypatch.setattr(DuckStore, "_bump_version", boom)
    rows = store.row_count("t")
    with pytest.raises(StoreError):
        store.append_rows("t", [("y",)])
    monkeypatch.undo()
    assert store.table_writing("t") is False
    assert store.row_count("t") == rows


def test_the_flag_is_cleared_when_the_second_bump_fails(store: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    original = DuckStore._bump_version
    calls: list[int] = []

    def second_fails(self: Any, name: str) -> None:
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("late bump failed")
        original(self, name)

    monkeypatch.setattr(DuckStore, "_bump_version", second_fails)
    with pytest.raises(RuntimeError):
        store.append_rows("t", [("y",)])
    monkeypatch.undo()
    assert store.table_writing("t") is False  # the rows are committed; the flag does not stay set


def test_the_reader_reports_the_store_flag_and_token(store: Any) -> None:
    reader = store.reader()
    try:
        assert reader.table_version("t") == store.table_version("t")
        assert reader.table_writing("t") is False
        store._set_writing("t", True)
        assert reader.table_writing("t") is True and reader.table_writing("u") is False
        store._set_writing("t", False)
        assert reader.table_writing("t") is False
        store._bump_version("t")
        assert reader.table_version("t") == store.table_version("t")
    finally:
        reader.close()
