"""Tests for StoreCandidate, the store-backed import candidate."""

from __future__ import annotations

import copy
import dataclasses
import threading

import pytest

from analytics_studio.file_import import ImportCandidate
from analytics_studio.store.candidate import (
    LARGE_TABLE_REFUSAL_TEXT,
    LargeTableError,
    StoreCandidate,
    large_table_context,
    large_table_message,
)


class _Session:
    """Stands in for ProjectStore: holds a thread lock, like the real one."""

    def __init__(self) -> None:
        self.lock = threading.Lock()


def _make(session=None, source_id=None) -> StoreCandidate:
    return StoreCandidate(
        "csv",
        ["Region", "Sales"],
        {"path": "C:/data/sales.csv", "delimiter": ","},
        ["note one"],
        store_table="sales_table",
        row_count=250_000,
        physical_types=["text", "decimal"],
        model_types={"Region": "Text", "Sales": "Decimal"},
        session=session,
        source_id=source_id,
    )


def test_is_import_candidate_subclass():
    assert isinstance(_make(), ImportCandidate)


def test_rows_raises_default_what():
    with pytest.raises(LargeTableError) as info:
        _ = _make().rows
    assert str(info.value) == (
        "This feature: this table is stored in the large-data store; "
        "this feature is not available for it yet"
    )


def test_rows_raises_custom_what_from_context():
    candidate = _make()
    with large_table_context("Pivot table"):
        with pytest.raises(LargeTableError) as info:
            _ = candidate.rows
    assert str(info.value).startswith("Pivot table: this table is stored")


def test_large_table_error_is_value_error():
    assert issubclass(LargeTableError, ValueError)
    with pytest.raises(ValueError):
        _ = _make().rows


def test_refusal_text_format():
    assert large_table_message("Export") == (
        "Export is not available for large-data tables yet. Tables up to 100,000 rows "
        "work everywhere; large tables support the data grid, sort, filter, column "
        "statistics and export. Other features arrive in a later release."
    )
    assert large_table_message("X") == LARGE_TABLE_REFUSAL_TEXT.format(what="X")


def test_context_restores_previous_what():
    candidate = _make()
    with large_table_context("Outer"):
        with large_table_context("Inner"):
            with pytest.raises(LargeTableError, match="^Inner:"):
                _ = candidate.rows
        with pytest.raises(LargeTableError, match="^Outer:"):
            _ = candidate.rows
    with pytest.raises(LargeTableError, match="^This feature:"):
        _ = candidate.rows


def test_context_restores_on_exception():
    with pytest.raises(RuntimeError):
        with large_table_context("Broken"):
            raise RuntimeError("boom")
    with pytest.raises(LargeTableError, match="^This feature:"):
        _ = _make().rows


def test_contextvar_is_not_seen_by_other_threads():
    seen: list[str] = []

    def worker() -> None:
        try:
            _ = _make().rows
        except LargeTableError as exc:
            seen.append(str(exc))

    with large_table_context("Main-thread feature"):
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
    assert len(seen) == 1
    assert seen[0].startswith("This feature:")


def test_bool_is_true_and_no_len_or_iter():
    candidate = _make()
    assert bool(candidate) is True
    assert not hasattr(type(candidate), "__len__")
    assert not hasattr(type(candidate), "__iter__")


def test_row_count_is_stored_int():
    candidate = _make()
    assert candidate.row_count == 250_000
    assert isinstance(candidate.row_count, int)


def test_row_count_has_no_setter():
    candidate = _make()
    with pytest.raises(AttributeError):
        candidate.row_count = 5


def test_rows_has_no_setter():
    candidate = _make()
    with pytest.raises(AttributeError):
        candidate.rows = []


def test_repr_eq_hash_do_not_touch_rows():
    candidate = _make()
    assert "sales_table" in repr(candidate)
    assert "250000" in repr(candidate)
    duplicate = copy.copy(candidate)
    assert candidate == duplicate
    assert hash(candidate) == hash(duplicate)
    assert {candidate: 1}[duplicate] == 1


def test_eq_differs_for_different_table():
    first = _make()
    second = StoreCandidate(
        "csv", ["Region", "Sales"], {"path": "C:/data/sales.csv"}, [],
        store_table="other_table", row_count=250_000,
        source_id=first.source_id,
    )
    assert first != second
    assert first != "not a candidate"


def test_copy_copy_shares_session_and_copies_lists():
    session = _Session()
    candidate = _make(session=session)
    clone = copy.copy(candidate)
    assert clone is not candidate
    assert clone.session is session
    assert clone.headers == candidate.headers
    assert clone.headers is not candidate.headers
    assert clone.notices is not candidate.notices
    assert clone.physical_types is not candidate.physical_types
    assert clone.model_types is not candidate.model_types
    assert clone.row_count == candidate.row_count


def test_deepcopy_shares_session_and_its_lock():
    session = _Session()
    candidate = _make(session=session)
    clone = copy.deepcopy(candidate)
    assert clone is not candidate
    assert clone.session is session
    assert clone.session.lock is session.lock
    assert clone.headers == ["Region", "Sales"]
    assert clone.headers is not candidate.headers
    assert clone.store_table == "sales_table"
    assert clone.row_count == 250_000


def test_deepcopy_with_no_session():
    candidate = _make(session=None)
    clone = copy.deepcopy(candidate)
    assert clone.session is None
    assert clone.options == candidate.options


def test_set_source_identity_sets_only_source_id():
    candidate = _make()
    before = dict(candidate.__dict__)
    candidate.set_source_identity("saved-source-id", preserve_origins=True)
    after = dict(candidate.__dict__)
    assert candidate.source_id == "saved-source-id"
    changed = {key for key in before if before[key] != after[key]}
    assert changed == {"source_id"}


def test_source_id_matches_import_candidate_for_same_inputs():
    headers = ["Region", "Sales"]
    options = {"path": "C:/data/sales.csv", "delimiter": ","}
    notices = ["note one"]
    candidate = StoreCandidate(
        "csv", headers, options, notices, store_table="t", row_count=3,
    )
    expected = ImportCandidate("csv", headers, [], options, notices).source_id
    assert candidate.source_id == expected
    assert candidate.source_id


def test_explicit_source_id_is_kept():
    candidate = _make(source_id="explicit-id")
    assert candidate.source_id == "explicit-id"


def test_is_store_backed_flag():
    assert getattr(_make(), "is_store_backed", False) is True
    plain = ImportCandidate("csv", ["a"], [], {}, [])
    assert getattr(plain, "is_store_backed", False) is False


def test_headers_options_notices_accessible():
    candidate = _make()
    assert candidate.kind == "csv"
    assert candidate.headers == ["Region", "Sales"]
    assert candidate.options["delimiter"] == ","
    assert candidate.notices == ["note one"]
    assert candidate.physical_types == ["text", "decimal"]
    assert candidate.model_types == {"Region": "Text", "Sales": "Decimal"}
    assert candidate.store_table == "sales_table"


def test_dataclass_helpers_raise_large_table_error():
    # asdict and replace read every parent field, including rows, so they refuse.
    candidate = _make()
    with pytest.raises(LargeTableError):
        dataclasses.asdict(candidate)
    with pytest.raises(LargeTableError):
        dataclasses.replace(candidate, notices=[])
