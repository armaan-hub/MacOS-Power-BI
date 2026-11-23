"""Tests for parquet_source: differential against the old Parquet importer.

Every supported type is compared cell by cell with ``_parse_parquet``; every
refusal is compared with the old parser's message where the old parser also
refuses, and asserted as an exact new message where the store path is stricter.
"""

from __future__ import annotations

import datetime
import threading
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest

from analytics_studio.file_import import (
    FileImportError,
    ImportCancelledError,
    _parse_parquet,
    default_options,
)

from analytics_studio.store import parquet_source
from analytics_studio.store.parquet_source import iter_parquet_batches, plan_parquet

TARGET_TYPES = {
    "boolean": pa.bool_(),
    "whole": pa.int64(),
    "decimal": pa.float64(),
    "fixed": pa.decimal128(19, 4),
    "datetime": pa.timestamp("us"),
    "text": pa.string(),
}


# ---------------------------------------------------------------- helpers


def write_table(tmp_path: Path, name: str, table: pa.Table, **kwargs) -> Path:
    path = Path(tmp_path) / name
    pq.write_table(table, path, **kwargs)
    return path


def parse_old(path: Path):
    return _parse_parquet(Path(path), default_options("parquet"))


def drain(path: Path, plan, **kwargs) -> list[pa.RecordBatch]:
    return list(iter_parquet_batches(Path(path), plan, **kwargs))


def batch_rows(batches: list[pa.RecordBatch], headers: list[str]) -> list[dict]:
    rows: list[dict] = []
    for batch in batches:
        columns = [batch.column(i).to_pylist() for i in range(batch.num_columns)]
        for index in range(batch.num_rows):
            rows.append({h: columns[i][index] for i, h in enumerate(headers)})
    return rows


def as_datetime(value):
    """Old-parser cell -> naive datetime (a date becomes midnight)."""
    if isinstance(value, datetime.datetime):
        return value
    if isinstance(value, datetime.date):
        return datetime.datetime(value.year, value.month, value.day)
    to_pydatetime = getattr(value, "to_pydatetime", None)  # pandas.Timestamp (ns)
    if to_pydatetime is not None:
        return to_pydatetime()
    return value


def normalize(value, store_type: str):
    if store_type == "fixed" and isinstance(value, Decimal):
        return value.quantize(Decimal("0.0001"))
    if store_type == "datetime":
        return as_datetime(value)
    return value


def assert_same_table(old, plan, batches) -> list[dict]:
    """Same headers, same row count, same value per cell after conversion."""
    assert plan.headers == old.headers
    assert plan.row_count == len(old.rows)
    assert sum(batch.num_rows for batch in batches) == plan.row_count
    new_rows = batch_rows(batches, plan.headers)
    assert len(new_rows) == len(old.rows)
    for row_number, (old_row, new_row) in enumerate(zip(old.rows, new_rows), 1):
        for header, store_type in zip(plan.headers, plan.column_types):
            assert normalize(old_row[header], store_type) == normalize(
                new_row[header], store_type
            ), (row_number, header, old_row[header], new_row[header])
    return new_rows


def supported_table() -> pa.Table:
    """Every source type the store path supports, including null cells."""
    return pa.table(
        {
            "flag": pa.array([True, False, None, True, False]),
            "i8": pa.array([1, -2, None, 4, 127], type=pa.int8()),
            "i16": pa.array([1, -2, None, 4, 300], type=pa.int16()),
            "i32": pa.array([1, -2, None, 4, 70000], type=pa.int32()),
            "i64": pa.array([1, -2, None, 4, 2**62], type=pa.int64()),
            "u8": pa.array([0, 1, None, 2, 255], type=pa.uint8()),
            "u16": pa.array([0, 1, None, 2, 65535], type=pa.uint16()),
            "u32": pa.array([0, 1, None, 2, 4000000000], type=pa.uint32()),
            "u64": pa.array([0, 1, None, 2, 2**63 - 1], type=pa.uint64()),
            "f32": pa.array([0.5, 1.25, -2.0, None, 0.1], type=pa.float32()),
            "f64": pa.array([0.5, 100.25, -2.0, None, 1e300], type=pa.float64()),
            "dec10": pa.array(
                [
                    Decimal("12345.67"),
                    Decimal("-1.05"),
                    None,
                    Decimal("0.00"),
                    Decimal("99999999.99"),
                ],
                type=pa.decimal128(10, 2),
            ),
            "dec19": pa.array(
                [
                    Decimal("1234567890123.4567"),
                    Decimal("-1.0001"),
                    None,
                    Decimal("0.0000"),
                    Decimal("9999999999999.9999"),
                ],
                type=pa.decimal128(19, 4),
            ),
            "s": pa.array(["héllo", "", "text", None, "unicode ✓ emoji 🎉"]),
            "dict_s": pa.array(
                ["a", "b", "a", None, "c"], type=pa.dictionary(pa.int8(), pa.string())
            ),
            "ls": pa.array(["large", "", None, "x", "y"], type=pa.large_string()),
            "d32": pa.array(
                [
                    datetime.date(2024, 1, 2),
                    datetime.date(1999, 12, 31),
                    None,
                    datetime.date(2024, 2, 29),
                    datetime.date(1, 1, 1),
                ],
                type=pa.date32(),
            ),
            "d64": pa.array(
                [
                    datetime.date(2024, 1, 2),
                    datetime.date(1999, 12, 31),
                    None,
                    datetime.date(2024, 2, 29),
                    datetime.date(1, 1, 1),
                ],
                type=pa.date64(),
            ),
            "tms": pa.array(
                [
                    datetime.datetime(2024, 1, 1, 12, 30, 15, 123000),
                    datetime.datetime(1970, 1, 1),
                    None,
                    datetime.datetime(2024, 6, 1, 1, 2, 3, 999999),
                    datetime.datetime(1, 1, 1),
                ],
                type=pa.timestamp("ms"),
            ),
            "tus": pa.array(
                [
                    datetime.datetime(2024, 1, 1, 12, 30, 15, 123456),
                    datetime.datetime(1970, 1, 1),
                    None,
                    datetime.datetime(2024, 6, 1, 1, 2, 3, 999999),
                    datetime.datetime(1, 1, 1),
                ],
                type=pa.timestamp("us"),
            ),
            # Whole-microsecond nanoseconds: fine for both paths.
            "tns": pa.array(
                [1700000000123456000, 0, None, 1000, 9223372036854775000],
                type=pa.timestamp("ns"),
            ),
            "nul": pa.array([None] * 5, type=pa.null()),
        }
    )


# ------------------------------------------------------------ differential


def test_supported_types_match_old_parser(tmp_path: Path):
    path = write_table(tmp_path, "all.parquet", supported_table())
    old = parse_old(path)
    plan = plan_parquet(path)
    batches = drain(path, plan)

    assert plan.column_types == [
        "boolean",
        "whole", "whole", "whole", "whole",
        "whole", "whole", "whole", "whole",
        "decimal", "decimal",
        "fixed", "fixed",
        "text", "text", "text",
        "datetime", "datetime", "datetime", "datetime", "datetime",
        "text",
    ]
    assert len(plan.notices) == 1
    new_rows = assert_same_table(old, plan, batches)

    # The yielded batches carry the plan's names and the store's Arrow types.
    assert [field.name for field in batches[0].schema] == plan.headers
    assert [field.type for field in batches[0].schema] == [
        TARGET_TYPES[store_type] for store_type in plan.column_types
    ]

    # Nulls stay nulls, empty strings stay empty strings.
    assert new_rows[2]["i8"] is None
    assert new_rows[3]["s"] is None
    assert new_rows[2]["nul"] is None
    assert new_rows[1]["s"] == ""
    assert new_rows[1]["ls"] == ""

    # float32 widens to the float64 of the stored float32, not of the literal.
    expected_f32 = pa.array([0.1], type=pa.float32())[0].as_py()
    assert new_rows[4]["f32"] == expected_f32
    assert expected_f32 != 0.1


def test_duplicate_and_blank_headers_match_old(tmp_path: Path):
    table = pa.Table.from_arrays(
        [pa.array([1, 2]), pa.array([3, 4]), pa.array([5, 6]), pa.array([7, 8])],
        names=["a", "", "  ", "a"],
    )
    path = write_table(tmp_path, "dupes.parquet", table)
    old = parse_old(path)
    plan = plan_parquet(path)
    batches = drain(path, plan)
    assert plan.headers == ["a", "Column 2", "Column 3", "a_2"]
    assert_same_table(old, plan, batches)


def test_zero_row_table_yields_no_batches(tmp_path: Path):
    table = pa.table(
        {"a": pa.array([], type=pa.int64()), "b": pa.array([], type=pa.string())}
    )
    path = write_table(tmp_path, "empty.parquet", table)
    old = parse_old(path)
    plan = plan_parquet(path)
    batches = drain(path, plan)
    assert plan.row_count == 0
    assert batches == []
    assert_same_table(old, plan, batches)


def test_multi_row_group_file_streams_and_totals_match(tmp_path: Path):
    count = 5_500
    table = pa.table(
        {
            "id": pa.array(range(count), type=pa.int64()),
            "label": pa.array([f"row-{i}" for i in range(count)]),
        }
    )
    path = write_table(tmp_path, "groups.parquet", table, row_group_size=1000)
    old = parse_old(path)
    plan = plan_parquet(path)
    batches = drain(path, plan, batch_size=1000)
    assert plan.row_count == count
    assert len(batches) > 1
    assert len({batch.num_rows for batch in batches}) > 1
    assert_same_table(old, plan, batches)


# --------------------------------------------------------------- refusals


def test_zero_column_file_refused_like_old(tmp_path: Path):
    path = write_table(tmp_path, "zero.parquet", pa.table({}))
    with pytest.raises(FileImportError) as old_info:
        parse_old(path)
    with pytest.raises(FileImportError) as new_info:
        plan_parquet(path)
    assert str(new_info.value) == str(old_info.value)
    assert str(new_info.value) == "Parquet import requires at least one column."


def test_missing_file_refused(tmp_path: Path):
    with pytest.raises(FileImportError, match="Could not read"):
        plan_parquet(Path(tmp_path) / "absent.parquet")


def test_uint64_above_signed_max_refused(tmp_path: Path):
    table = pa.table({"big": pa.array([1, 2**63, 3], type=pa.uint64())})
    path = write_table(tmp_path, "u64.parquet", table)
    plan = plan_parquet(path)
    assert plan.column_types == ["whole"]
    with pytest.raises(FileImportError) as info:
        drain(path, plan)
    message = str(info.value)
    assert "'big'" in message
    assert "9223372036854775807" in message
    assert "row 2" in message


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_float_refused_like_old(tmp_path: Path, value: float):
    table = pa.table({"f": pa.array([1.0, value, 3.0])})
    path = write_table(tmp_path, "nonfinite.parquet", table)
    plan = plan_parquet(path)
    assert plan.column_types == ["decimal"]
    with pytest.raises(FileImportError) as old_info:
        parse_old(path)
    with pytest.raises(FileImportError) as new_info:
        drain(path, plan)
    assert str(new_info.value) == str(old_info.value)
    assert str(new_info.value) == "Parquet column 'f' contains a non-finite number."


@pytest.mark.parametrize(
    "precision, scale, value",
    [(20, 6, "1.123456"), (38, 0, "12345")],
)
def test_decimal_too_wide_for_fixed_refused(tmp_path: Path, precision: int, scale: int, value: str):
    table = pa.table(
        {"d": pa.array([Decimal(value)], type=pa.decimal128(precision, scale))}
    )
    path = write_table(tmp_path, f"dec{precision}_{scale}.parquet", table)
    with pytest.raises(FileImportError) as info:
        plan_parquet(path)
    assert str(info.value) == (
        f"Parquet decimal column 'd' (decimal({precision},{scale})) "
        "does not fit the 4-decimal fixed type"
    )


def test_time_zone_refused(tmp_path: Path):
    table = pa.table(
        {
            "when": pa.array(
                [datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)],
                type=pa.timestamp("us", tz="UTC"),
            )
        }
    )
    path = write_table(tmp_path, "tz.parquet", table)
    # The old parser accepts it; the store path refuses before reading rows.
    assert parse_old(path).rows
    with pytest.raises(FileImportError) as info:
        plan_parquet(path)
    assert str(info.value) == (
        "Parquet column 'when' has a time zone; remove the time zone before importing"
    )


@pytest.mark.parametrize("arrow_type", [pa.time32("s"), pa.time64("us")])
def test_time_of_day_refused(tmp_path: Path, arrow_type: pa.DataType):
    table = pa.table({"t": pa.array([datetime.time(1, 2, 3)], type=arrow_type)})
    path = write_table(tmp_path, f"{str(arrow_type).replace('[', '_').replace(']', '')}.parquet", table)
    assert parse_old(path).rows  # old accepts time-of-day values
    with pytest.raises(FileImportError) as info:
        plan_parquet(path)
    assert str(info.value) == (
        "Parquet column 't' has a time-of-day type that the large-table store "
        "does not support yet"
    )


@pytest.mark.parametrize(
    "values",
    [pa.array([[1, 2]]), pa.array([{"a": 1}]), pa.array([b"xy"]), pa.array([b"xy"], type=pa.large_binary())],
)
def test_nested_and_binary_refused_like_old(tmp_path: Path, values: pa.Array):
    table = pa.Table.from_arrays([values], names=["col"])
    path = write_table(tmp_path, f"nested_{values.type}.parquet".replace("/", "-"), table)
    with pytest.raises(FileImportError) as old_info:
        parse_old(path)
    with pytest.raises(FileImportError) as new_info:
        plan_parquet(path)
    assert str(new_info.value) == str(old_info.value)
    assert "unsupported type" in str(new_info.value)


def test_sub_microsecond_timestamp_refused(tmp_path: Path):
    table = pa.table(
        {"ts": pa.array([1700000000123456789], type=pa.timestamp("ns"))}
    )
    path = write_table(tmp_path, "ns.parquet", table)
    plan = plan_parquet(path)  # type decision itself is fine
    assert plan.column_types == ["datetime"]
    # The old parser hands the caller a truncated value; the store path refuses.
    assert parse_old(path).rows
    with pytest.raises(FileImportError) as info:
        drain(path, plan)
    message = str(info.value)
    assert "'ts'" in message
    assert "microsecond" in message


def test_single_oversized_row_group_refused(tmp_path: Path):
    """Only a single row group is capped; the file's total size is not."""
    table = pa.table({"a": pa.array(range(200_000), type=pa.int64())})
    path = write_table(tmp_path, "wide.parquet", table)
    # One ~1.6 MiB row group: fine against the default 1 GiB per-group budget.
    assert plan_parquet(path).row_count == 200_000

    with pytest.raises(FileImportError) as info:
        plan_parquet(path, max_row_group_bytes=1_000_000)
    assert str(info.value) == (
        "wide.parquet has a Parquet row group larger than "
        f"{1_000_000 // (1024 * 1024)} MiB; the store import reads one row group "
        "at a time."
    )

    with pytest.raises(FileImportError) as one_mib:
        plan_parquet(path, max_row_group_bytes=1_048_576)
    assert str(one_mib.value) == (
        "wide.parquet has a Parquet row group larger than 1 MiB; "
        "the store import reads one row group at a time."
    )


def test_total_over_old_80_mib_budget_still_imports(tmp_path: Path):
    """The old whole-file budget is gone: only one row group is capped."""
    # 1.8M rows produces ~93 MB uncompressed (> 80 MiB) across 18 row groups, running in < 1s
    rows = 1_800_000
    ids = pa.array(range(rows), type=pa.int64())
    floats = pc.multiply(pc.cast(ids, pa.float64()), 0.37)
    table = pa.table(
        {
            "i": ids,
            "f": floats,
            "s": pc.cast(pc.add(pc.multiply(ids, 31), 17), pa.string()),
            "ts": pc.cast(
                pc.add(
                    pc.multiply(ids, 1_000_000),
                    pa.scalar(1704067200000000, type=pa.int64()),
                ),
                pa.timestamp("us"),
            ),
            "d": pc.cast(floats, pa.decimal128(12, 2), safe=True),
        }
    )
    path = write_table(tmp_path, "many.parquet", table, row_group_size=100_000)

    metadata = pq.ParquetFile(path).metadata
    group_bytes = [
        metadata.row_group(i).total_byte_size for i in range(metadata.num_row_groups)
    ]
    assert sum(group_bytes) > 80 * 1024 * 1024  # premise: over the old 80 MiB budget
    assert len(group_bytes) == 18
    assert max(group_bytes) < 1024**3  # ... but every group fits the per-group cap

    plan = plan_parquet(path)
    batches = drain(path, plan, batch_size=100_000)
    assert plan.row_count == rows
    assert len(batches) >= 18
    assert sum(batch.num_rows for batch in batches) == rows
    assert [field.type for field in batches[0].schema] == [
        pa.int64(),
        pa.float64(),
        pa.string(),
        pa.timestamp("us"),
        pa.decimal128(19, 4),
    ]


def test_row_group_count_sanity_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    table = pa.table({"a": pa.array(range(5_000), type=pa.int64())})
    path = write_table(tmp_path, "groups.parquet", table, row_group_size=1000)
    plan = plan_parquet(path)  # six row groups are fine by default
    assert plan.row_count == 5_000
    monkeypatch.setattr(parquet_source, "MAX_DATA_ROWS", 2)
    with pytest.raises(FileImportError) as info:
        plan_parquet(path)
    assert str(info.value) == "groups.parquet contains more than 2 Parquet row groups."


def test_old_row_and_cell_limits_are_not_applied(tmp_path: Path):
    """The store caller owns max_rows, so the old 100k-row/500k-cell caps are gone."""
    rows = 300_000  # x 2 columns = 600,000 cells, over the old 500,000-cell cap
    table = pa.table(
        {
            "a": pa.array(range(rows), type=pa.int64()),
            "b": pa.array([1.5] * rows, type=pa.float64()),
        }
    )
    path = write_table(tmp_path, "many.parquet", table)
    with pytest.raises(FileImportError):
        parse_old(path)  # old importer stops at its own row/cell limits
    plan = plan_parquet(path)
    batches = drain(path, plan)
    assert plan.row_count == rows
    assert sum(batch.num_rows for batch in batches) == rows
    assert [field.type for field in batches[0].schema] == [pa.int64(), pa.float64()]


def test_plan_header_mismatch_refused(tmp_path: Path):
    table = pa.table({"a": pa.array([1, 2], type=pa.int64()), "b": pa.array([3, 4])})
    path = write_table(tmp_path, "mismatch.parquet", table)
    plan = plan_parquet(path)
    short = replace(plan, headers=["a"], column_types=["whole"])
    with pytest.raises(FileImportError) as info:
        drain(path, short)
    assert "inconsistent Parquet batch columns" in str(info.value)


# ----------------------------------------------------- cancel, progress, lies


def test_cancel_before_second_batch(tmp_path: Path):
    table = pa.table({"a": pa.array(range(5_000), type=pa.int64())})
    path = write_table(tmp_path, "cancel.parquet", table)
    plan = plan_parquet(path)

    event = threading.Event()
    plan_event = threading.Event()
    plan_event.set()
    with pytest.raises(ImportCancelledError) as plan_info:
        plan_parquet(path, cancel_event=plan_event)
    assert str(plan_info.value) == "Import canceled."

    generator = iter_parquet_batches(path, plan, cancel_event=event, batch_size=1000)
    first = next(generator)
    assert first.num_rows == 1000
    event.set()
    with pytest.raises(ImportCancelledError) as info:
        next(generator)
    assert str(info.value) == "Import canceled."


def test_progress_called_once_per_batch(tmp_path: Path):
    count = 120_000
    table = pa.table(
        {
            "a": pa.array(range(count), type=pa.int64()),
            "b": pa.array([1.5] * count, type=pa.float64()),
        }
    )
    path = write_table(tmp_path, "progress.parquet", table)
    plan = plan_parquet(path)
    messages: list[str] = []
    batches = drain(path, plan, progress=messages.append)
    assert sum(batch.num_rows for batch in batches) == count
    assert len(messages) >= 2
    assert len(messages) == len(batches)
    assert messages[0] == f"Read {50_000:,} Parquet rows…"
    assert messages[-1] == f"Read {count:,} Parquet rows…"


def test_declared_row_count_must_equal_yielded_rows(tmp_path: Path):
    table = pa.table({"a": pa.array(range(10), type=pa.int64())})
    path = write_table(tmp_path, "lie.parquet", table)
    plan = plan_parquet(path)
    assert plan.row_count == 10

    for wrong in (11, 0, -1):
        lying = replace(plan, row_count=wrong)
        with pytest.raises(FileImportError) as info:
            drain(path, lying)
        assert str(info.value) == (
            f"lie.parquet declares {wrong:,} rows but yielded 10."
        )


@pytest.mark.parametrize(
    "name,arr",
    [
        ("date32_past", pa.array([-719163], type=pa.date32())),
        ("date32_future", pa.array([2932897], type=pa.date32())),
        ("date64_past", pa.array([-62135683200000], type=pa.date64())),
        ("date64_future", pa.array([253402300800000], type=pa.date64())),
        ("ts_s_future", pa.array([253402300800], type=pa.timestamp("s"))),
        ("ts_s_past", pa.array([-62135596801], type=pa.timestamp("s"))),
        ("ts_ms_future", pa.array([253402300800000], type=pa.timestamp("ms"))),
        ("ts_ms_past", pa.array([-65000000000000], type=pa.timestamp("ms"))),
        ("ts_us_future", pa.array([2**62], type=pa.timestamp("us"))),
        ("ts_us_past", pa.array([-2**63 + 1], type=pa.timestamp("us"))),
    ],
)
def test_datetime_outside_year_1_to_9999_refused(tmp_path: Path, name: str, arr: pa.Array):
    table = pa.table({"d": arr})
    path = write_table(tmp_path, f"{name}.parquet", table)
    plan = plan_parquet(path)
    assert plan.column_types == ["datetime"]
    with pytest.raises(FileImportError) as info:
        drain(path, plan)
    msg = str(info.value)
    assert "outside years 1 to 9999" in msg
    assert "row 1" in msg


def test_datetime_outside_year_1_to_9999_row_number(tmp_path: Path):
    table = pa.table(
        {
            "ts": pa.concat_arrays(
                [
                    pa.array(
                        [
                            datetime.datetime(2020, 1, 1),
                            datetime.datetime(2020, 1, 2),
                            None,
                        ],
                        type=pa.timestamp("ms"),
                    ),
                    pa.array([253402300800000], type=pa.timestamp("ms")),
                ]
            )
        }
    )
    path = write_table(tmp_path, "late_ts.parquet", table)
    plan = plan_parquet(path)
    with pytest.raises(FileImportError) as info:
        drain(path, plan)
    msg = str(info.value)
    assert "row 4" in msg


def test_decimal_precision_scale_limits(tmp_path: Path):
    # decimal(20,4) -> precision - scale = 16 > 15 -> refused
    t_bad = pa.table({"d": pa.array([Decimal("1.0")], type=pa.decimal128(20, 4))})
    p_bad = write_table(tmp_path, "dec20_4.parquet", t_bad)
    with pytest.raises(FileImportError) as info:
        plan_parquet(p_bad)
    assert "does not fit the 4-decimal fixed type" in str(info.value)

    # decimal(19,4) -> precision - scale = 15 <= 15 -> accepted
    t_ok = pa.table({"d": pa.array([Decimal("1.0")], type=pa.decimal128(19, 4))})
    p_ok = write_table(tmp_path, "dec19_4.parquet", t_ok)
    plan = plan_parquet(p_ok)
    assert plan.column_types == ["fixed"]

