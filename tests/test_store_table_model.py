"""Differential test suite comparing StoreTableModel against CsvTableModel."""

import datetime
import decimal
import os
import random
import threading
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtTest import QAbstractItemModelTester

from analytics_studio.controller import CsvTableModel
from analytics_studio.file_import import ImportCancelledError
from analytics_studio.store import DuckStore, StoreTableModel


@pytest.fixture(scope="session")
def qapp():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


def _assert_models_identical(csv_model: CsvTableModel, store_model: StoreTableModel, message: str = ""):
    """Assert all observable state between CsvTableModel and StoreTableModel is identical."""
    assert csv_model.rowCount() == store_model.rowCount(), f"rowCount mismatch: {message}"
    assert csv_model.columnCount() == store_model.columnCount(), f"columnCount mismatch: {message}"
    assert csv_model.pageCount == store_model.pageCount, f"pageCount mismatch: {message}"
    assert csv_model.currentPage == store_model.currentPage, f"currentPage mismatch: {message}"
    assert csv_model.pageRange == store_model.pageRange, f"pageRange mismatch: {message}"
    assert csv_model.canGoPrevious == store_model.canGoPrevious, f"canGoPrevious mismatch: {message}"
    assert csv_model.canGoNext == store_model.canGoNext, f"canGoNext mismatch: {message}"
    assert csv_model.sortColumn == store_model.sortColumn, f"sortColumn mismatch: {message}"
    assert csv_model.sortDirection == store_model.sortDirection, f"sortDirection mismatch: {message}"
    assert sorted(csv_model.activeFilterColumns) == sorted(store_model.activeFilterColumns), f"activeFilterColumns mismatch: {message}"

    headers = [csv_model.headerData(c, Qt.Orientation.Horizontal) for c in range(csv_model.columnCount())]
    store_headers = [store_model.headerData(c, Qt.Orientation.Horizontal) for c in range(store_model.columnCount())]
    assert headers == store_headers, f"headers mismatch: {message}"

    for r in range(csv_model.rowCount()):
        assert csv_model.headerData(r, Qt.Orientation.Vertical) == store_model.headerData(r, Qt.Orientation.Vertical)
        for c in range(csv_model.columnCount()):
            idx_csv = csv_model.index(r, c)
            idx_store = store_model.index(r, c)
            val_csv = csv_model.data(idx_csv, Qt.ItemDataRole.DisplayRole)
            val_store = store_model.data(idx_store, Qt.ItemDataRole.DisplayRole)
            assert val_csv == val_store, (
                f"data cell ({r}, {c}) '{headers[c]}' mismatch: csv='{val_csv}', store='{val_store}': {message}"
            )


def test_qabstract_item_model_tester(tmp_path, qapp):
    """Verify StoreTableModel adheres to Qt abstract model invariants."""
    db_path = str(tmp_path / "tester.duckdb")
    with DuckStore(db_path) as store:
        store.create_table("t", [("id", "whole"), ("name", "text")])
        store.append_rows("t", [(1, "Alpha"), (2, "Beta")])
        model = StoreTableModel(store)
        model.replace_data("t")
        tester = QAbstractItemModelTester(model)
        assert tester is not None
        assert model.rowCount() == 2
        assert model.columnCount() == 2


def test_empty_and_single_row_tables(tmp_path, qapp):
    db_path = str(tmp_path / "empty_single.duckdb")
    with DuckStore(db_path) as store:
        store.create_table("empty_tbl", [("id", "whole"), ("val", "text")])
        csv_m = CsvTableModel()
        store_m = StoreTableModel(store)

        # Empty table
        csv_m.replace_data(["id", "val"], [])
        store_m.replace_data("empty_tbl")
        _assert_models_identical(csv_m, store_m, "empty table")

        # 1 row table
        store.create_table("single_tbl", [("id", "whole"), ("val", "text")])
        store.append_rows("single_tbl", [(42, "One")])
        csv_m.replace_data(["id", "val"], [{"id": 42, "val": "One"}])
        store_m.replace_data("single_tbl")
        _assert_models_identical(csv_m, store_m, "single row table")


def test_boundary_row_counts_500_501_1000_1001(tmp_path, qapp):
    db_path = str(tmp_path / "boundaries.duckdb")
    with DuckStore(db_path) as store:
        for count in [500, 501, 1000, 1001]:
            tbl = f"t_{count}"
            store.create_table(tbl, [("n", "whole"), ("label", "text")])
            rows = [(i, f"item_{i}") for i in range(count)]
            dict_rows = [{"n": r[0], "label": r[1]} for r in rows]
            store.append_rows(tbl, rows)

            csv_m = CsvTableModel()
            store_m = StoreTableModel(store)
            csv_m.replace_data(["n", "label"], dict_rows)
            store_m.replace_data(tbl)

            _assert_models_identical(csv_m, store_m, f"boundary count {count} page 0")

            if csv_m.pageCount > 1:
                # Next page
                csv_m.nextPage()
                store_m.nextPage()
                _assert_models_identical(csv_m, store_m, f"boundary count {count} page 1")

                # Last page
                last_p = csv_m.pageCount - 1
                csv_m._set_page(last_p)
                store_m._set_page(last_p)
                _assert_models_identical(csv_m, store_m, f"boundary count {count} last page")


def test_rich_column_types_differential(tmp_path, qapp):
    """Test with 8 column types covering whole, decimal, fixed, datetime, text, boolean, nulls."""
    db_path = str(tmp_path / "rich_types.duckdb")
    with DuckStore(db_path) as store:
        cols = [
            ("col_whole", "whole"),
            ("col_decimal", "decimal"),
            ("col_fixed", "fixed"),
            ("col_datetime", "datetime"),
            ("col_date", "datetime"),  # mapped to date in app
            ("col_text", "text"),
            ("col_bool", "boolean"),
            ("col_id", "whole"),
        ]
        store.create_table("rich", cols)

        col_types = {
            "col_whole": "whole_number",
            "col_decimal": "decimal_number",
            "col_fixed": "decimal_number",
            "col_datetime": "datetime",
            "col_date": "date",
            "col_text": "text",
            "col_bool": "boolean",
            "col_id": "whole_number",
        }

        raw_rows = [
            (
                100,
                12.345,
                decimal.Decimal("99.9900"),
                datetime.datetime(2026, 11, 23, 11, 30, 45),
                datetime.datetime(2026, 1, 15, 0, 0, 0),
                "Apple",
                True,
                1,
            ),
            (
                -50,
                -0.001,
                decimal.Decimal("-123.4560"),
                datetime.datetime(2025, 5, 10, 8, 0, 0),
                datetime.datetime(2025, 5, 10, 0, 0, 0),
                "banana",
                False,
                2,
            ),
            (
                0,
                0.0,
                decimal.Decimal("0.0000"),
                datetime.datetime(2000, 1, 1, 0, 0, 0),
                datetime.datetime(2000, 1, 1, 0, 0, 0),
                "ORANGE",
                True,
                3,
            ),
            (
                9223372036854775807,
                1e12,
                decimal.Decimal("999999999999999.9999"),
                datetime.datetime(2099, 12, 31, 23, 59, 59),
                datetime.datetime(2099, 12, 31, 0, 0, 0),
                "Grape",
                False,
                4,
            ),
            (
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                5,
            ),
            (
                20,
                12.345,
                decimal.Decimal("50.0000"),
                datetime.datetime(2026, 11, 23, 11, 30, 45),
                datetime.datetime(2026, 11, 23, 0, 0, 0),
                "",
                True,
                6,
            ),
        ]

        store.append_rows("rich", raw_rows)
        headers = [c[0] for c in cols]
        dict_rows = []
        for r in raw_rows:
            d = dict(zip(headers, r))
            if d.get("col_date") is not None:
                d["col_date"] = d["col_date"].date()
            dict_rows.append(d)

        csv_m = CsvTableModel()
        store_m = StoreTableModel(store)

        csv_m.replace_data(headers, dict_rows, column_types=col_types)
        store_m.replace_data("rich", headers, column_types=col_types)

        _assert_models_identical(csv_m, store_m, "initial rich load")

        # Sort ascending and descending on every column
        for idx, col in enumerate(headers):
            csv_m.sortByColumn(idx)
            store_m.sortByColumn(idx)
            _assert_models_identical(csv_m, store_m, f"sort asc {col}")

            csv_m.sortByColumn(idx)
            store_m.sortByColumn(idx)
            _assert_models_identical(csv_m, store_m, f"sort desc {col}")

        # Clear sort
        csv_m._sort_column = ""
        csv_m._apply_sort()
        csv_m._update_page_rows()
        store_m._sort_column = ""
        store_m._materialize_state()
        store_m._load_page_rows()

        # Every filter operator
        filter_tests = [
            ("col_whole", "equals", "100"),
            ("col_whole", "not_equals", "100"),
            ("col_whole", "greater_than", "0"),
            ("col_whole", "less_than_or_equal", "20"),
            ("col_whole", "is_null", ""),
            ("col_whole", "is_not_null", ""),
            ("col_decimal", "greater_than", "0.0"),
            ("col_decimal", "less_than", "10.0"),
            ("col_fixed", "equals", "99.99"),
            ("col_text", "contains", "an"),
            ("col_text", "begins_with", "app"),
            ("col_text", "ends_with", "E"),
            ("col_text", "is_blank", ""),
            ("col_text", "is_not_blank", ""),
            ("col_bool", "equals", "true"),
            ("col_bool", "equals", "false"),
            ("col_date", "greater_than", "2020-01-01"),
            ("col_datetime", "less_than", "2026-01-01T00:00:00"),
        ]

        for col, op, val in filter_tests:
            csv_m.setColumnFilter(col, op, val)
            store_m.setColumnFilter(col, op, val)
            _assert_models_identical(csv_m, store_m, f"filter {col} {op} {val}")
            csv_m.clearColumnFilter(col)
            store_m.clearColumnFilter(col)
            _assert_models_identical(csv_m, store_m, f"clear filter {col}")

        # Combined filters on two columns
        csv_m.setColumnFilter("col_whole", "greater_than", "-100")
        store_m.setColumnFilter("col_whole", "greater_than", "-100")
        csv_m.setColumnFilter("col_text", "contains", "a")
        store_m.setColumnFilter("col_text", "contains", "a")
        _assert_models_identical(csv_m, store_m, "combined two column filter")

        # Distinct filter values
        vals_csv = csv_m.columnFilterValues("col_text", "")
        vals_store = store_m.columnFilterValues("col_text", "")
        assert vals_csv == vals_store, "columnFilterValues mismatch"

        csv_m.clearColumnFilter("col_whole")
        store_m.clearColumnFilter("col_whole")
        csv_m.clearColumnFilter("col_text")
        store_m.clearColumnFilter("col_text")


def test_value_filter_operator_all_combinations(tmp_path, qapp):
    db_path = str(tmp_path / "value_filter.duckdb")
    with DuckStore(db_path) as store:
        store.create_table("t", [("category", "text"), ("amount", "whole")])
        rows = [
            ("Alpha", 10),
            ("Beta", 20),
            ("Gamma", 30),
            (None, 40),
        ]
        store.append_rows("t", rows)
        dict_rows = [{"category": r[0], "amount": r[1]} for r in rows]

        csv_m = CsvTableModel()
        store_m = StoreTableModel(store)
        csv_m.replace_data(["category", "amount"], dict_rows)
        store_m.replace_data("t")

        # Read available keys
        avail = csv_m.columnFilterValues("category", "")
        keys = [item["key"] for item in avail["values"]]

        # Include subset (all=False)
        subset = [keys[0], keys[1]]
        csv_m.setColumnValueFilter("category", False, subset)
        store_m.setColumnValueFilter("category", False, subset)
        _assert_models_identical(csv_m, store_m, "values filter all=False")

        # Exclude subset (all=True)
        csv_m.setColumnValueFilter("category", True, subset)
        store_m.setColumnValueFilter("category", True, subset)
        _assert_models_identical(csv_m, store_m, "values filter all=True")

        # Clear
        csv_m.clearColumnFilter("category")
        store_m.clearColumnFilter("category")
        _assert_models_identical(csv_m, store_m, "clear values filter")


def test_table_key_per_table_memory_and_pruning(tmp_path, qapp):
    db_path = str(tmp_path / "table_key.duckdb")
    with DuckStore(db_path) as store:
        store.create_table("t1", [("a", "whole"), ("b", "text")])
        store.create_table("t2", [("x", "whole"), ("y", "text")])
        store.append_rows("t1", [(1, "one"), (2, "two")])
        store.append_rows("t2", [(10, "ten"), (20, "twenty")])

        d1 = [{"a": 1, "b": "one"}, {"a": 2, "b": "two"}]
        d2 = [{"x": 10, "y": "ten"}, {"x": 20, "y": "twenty"}]

        csv_m = CsvTableModel()
        store_m = StoreTableModel(store)

        # Set sort on t1
        csv_m.replace_data(["a", "b"], d1, table_key="key1")
        store_m.replace_data("t1", table_key="key1")
        csv_m.sortByColumn(0)
        store_m.sortByColumn(0)
        _assert_models_identical(csv_m, store_m, "t1 sorted")

        # Switch to t2
        csv_m.replace_data(["x", "y"], d2, table_key="key2")
        store_m.replace_data("t2", table_key="key2")
        _assert_models_identical(csv_m, store_m, "t2 initial")

        # Switch back to t1: sort must be remembered
        csv_m.replace_data(["a", "b"], d1, table_key="key1")
        store_m.replace_data("t1", table_key="key1")
        _assert_models_identical(csv_m, store_m, "t1 remembered sort")

        # Prune stale keys
        keys_info = csv_m.columnFilterValues("b", "")
        k_all = [item["key"] for item in keys_info["values"]]
        csv_m.setColumnValueFilter("b", False, k_all + ["__stale_key__"])
        store_m.setColumnValueFilter("b", False, k_all + ["__stale_key__"])
        _assert_models_identical(csv_m, store_m, "pruned stale filter keys")


def test_large_table_100k_rows_sort_and_filter(tmp_path, qapp):
    """Test with 100,000 rows as required by brief."""
    db_path = str(tmp_path / "large_100k.duckdb")
    with DuckStore(db_path) as store:
        store.create_table("t100k", [("id", "whole"), ("val", "whole"), ("cat", "text")])
        # Generate 100,000 rows
        categories = ["Alpha", "Beta", "Gamma", "Delta"]
        batch_size = 20_000
        for b in range(5):
            rows = [
                (b * batch_size + i, (b * batch_size + i) % 500, categories[(i + b) % 4])
                for i in range(batch_size)
            ]
            store.append_rows("t100k", rows)

        assert store.row_count("t100k") == 100_000

        store_m = StoreTableModel(store)
        store_m.replace_data("t100k")
        assert store_m.pageCount == 200
        assert store_m.rowCount() == 500

        # Jump to last page
        store_m._set_page(199)
        assert store_m.currentPage == 200
        assert store_m.rowCount() == 500

        # Sort by val descending
        store_m.sortByColumn(1)  # val asc
        store_m.sortByColumn(1)  # val desc
        assert store_m.sortColumn == "val"
        assert store_m.sortDirection == "descending"

        # Apply filter cat = 'Alpha'
        store_m.setColumnFilter("cat", "equals", "Alpha")
        assert store_m.isColumnFiltered("cat")
        assert store_m._filtered_rows == 25_000
        assert store_m.pageCount == 50

        # Jump to last page of filtered
        store_m._set_page(49)
        assert store_m.currentPage == 50
        assert store_m.rowCount() == 500


def test_temp_table_cleanup(tmp_path, qapp):
    """Assert temp tables are dropped after clear/replace/destroy."""
    db_path = str(tmp_path / "cleanup.duckdb")
    with DuckStore(db_path) as store:
        store.create_table("t", [("a", "whole")])
        store.append_rows("t", [(1,), (2,), (3,)])

        model = StoreTableModel(store)
        model.replace_data("t")
        model.sortByColumn(0)  # Creates temp view
        cnt = store.execute("SELECT count(*) FROM duckdb_tables() WHERE temporary")
        assert cnt[0][0] == 1

        # Replace data drops view
        model.replace_data("t")
        cnt = store.execute("SELECT count(*) FROM duckdb_tables() WHERE temporary")
        assert cnt[0][0] == 0

        # Filter creates view
        model.setColumnFilter("a", "greater_than", "1")
        cnt = store.execute("SELECT count(*) FROM duckdb_tables() WHERE temporary")
        assert cnt[0][0] == 1

        # Clear drops view
        model.clear()
        cnt = store.execute("SELECT count(*) FROM duckdb_tables() WHERE temporary")
        assert cnt[0][0] == 0


def test_stable_order_on_ties(tmp_path, qapp):
    """Assert ties keep original __rn order (stable sort)."""
    db_path = str(tmp_path / "ties.duckdb")
    with DuckStore(db_path) as store:
        store.create_table("t", [("val", "whole"), ("tag", "text")])
        data = [
            (10, "first"),
            (20, "second"),
            (10, "third"),
            (10, "fourth"),
            (5, "fifth"),
        ]
        store.append_rows("t", data)
        dict_data = [{"val": r[0], "tag": r[1]} for r in data]

        csv_m = CsvTableModel()
        store_m = StoreTableModel(store)
        csv_m.replace_data(["val", "tag"], dict_data)
        store_m.replace_data("t")

        # Sort asc
        csv_m.sortByColumn(0)
        store_m.sortByColumn(0)
        _assert_models_identical(csv_m, store_m, "stable order asc")

        # Sort desc
        csv_m.sortByColumn(0)
        store_m.sortByColumn(0)
        _assert_models_identical(csv_m, store_m, "stable order desc")


def test_cancel_event_handling(tmp_path, qapp):
    """Assert cancel_event raises ImportCancelledError and cleans up temp table."""
    db_path = str(tmp_path / "cancel.duckdb")
    with DuckStore(db_path) as store:
        store.create_table("t", [("x", "text")])
        store.append_rows("t", [("A",), ("B",)])
        model = StoreTableModel(store)

        evt = threading.Event()
        evt.set()  # Cancelled immediately

        with pytest.raises(ImportCancelledError):
            model.replace_data("t", cancel_event=evt)

        cnt = store.execute("SELECT count(*) FROM duckdb_tables() WHERE temporary")
        assert cnt[0][0] == 0


def test_fuzz_200_seeded_combinations(tmp_path, qapp):
    """200 seeded random (data, sort, filter) combinations compared field by field."""
    rng = random.Random(42)
    db_path = str(tmp_path / "fuzz.duckdb")

    with DuckStore(db_path) as store:
        for trial in range(200):
            tbl_name = f"fuzz_{trial}"
            # Pick 2-4 columns
            col_candidates = [
                ("w", "whole", "whole_number"),
                ("d", "decimal", "decimal_number"),
                ("s", "text", "text"),
                ("b", "boolean", "boolean"),
            ]
            chosen_cols = rng.sample(col_candidates, k=rng.randint(2, 4))
            store_cols = [(c[0], c[1]) for c in chosen_cols]
            col_types = {c[0]: c[2] for c in chosen_cols}
            store.create_table(tbl_name, store_cols)

            row_count = rng.randint(5, 50)
            rows = []
            for _ in range(row_count):
                row = []
                for c_name, c_type, _ in chosen_cols:
                    if rng.random() < 0.15:
                        row.append(None)
                    elif c_type == "whole":
                        row.append(rng.randint(-100, 100))
                    elif c_type == "decimal":
                        row.append(round(rng.uniform(-100, 100), 2))
                    elif c_type == "text":
                        row.append(rng.choice(["apple", "Banana", "Cherry", "date", "", "123"]))
                    elif c_type == "boolean":
                        row.append(rng.choice([True, False]))
                rows.append(tuple(row))

            store.append_rows(tbl_name, rows)
            headers = [c[0] for c in chosen_cols]
            dict_rows = [dict(zip(headers, r)) for r in rows]

            csv_m = CsvTableModel()
            store_m = StoreTableModel(store)
            csv_m.replace_data(headers, dict_rows, column_types=col_types)
            store_m.replace_data(tbl_name, headers, column_types=col_types)

            _assert_models_identical(csv_m, store_m, f"fuzz {trial} initial")

            # Random sort
            if rng.random() < 0.7:
                sort_col_idx = rng.randint(0, len(headers) - 1)
                csv_m.sortByColumn(sort_col_idx)
                store_m.sortByColumn(sort_col_idx)
                if rng.random() < 0.5:
                    csv_m.sortByColumn(sort_col_idx)
                    store_m.sortByColumn(sort_col_idx)
                _assert_models_identical(csv_m, store_m, f"fuzz {trial} sort")

            # Random filter
            if rng.random() < 0.7:
                filt_col = rng.choice(headers)
                filt_type = col_types[filt_col]
                if filt_type == "whole_number":
                    op = rng.choice(["equals", "greater_than", "less_than", "is_null", "is_not_null"])
                    val = str(rng.randint(-50, 50))
                elif filt_type == "decimal_number":
                    op = rng.choice(["equals", "greater_than", "less_than", "is_null", "is_not_null"])
                    val = str(round(rng.uniform(-50, 50), 2))
                elif filt_type == "text":
                    op = rng.choice(["contains", "begins_with", "ends_with", "is_blank", "is_not_blank", "equals"])
                    val = rng.choice(["a", "b", "c", "1"])
                elif filt_type == "boolean":
                    op = rng.choice(["equals", "is_null", "is_not_null"])
                    val = rng.choice(["true", "false"])
                else:
                    op = "is_null"
                    val = ""

                csv_m.setColumnFilter(filt_col, op, val)
                store_m.setColumnFilter(filt_col, op, val)
                _assert_models_identical(csv_m, store_m, f"fuzz {trial} filter {filt_col} {op} {val}")


from analytics_studio.transformations import infer_column_types

def test_all_text_store_main_fixture(tmp_path, qapp):
    db_path = str(tmp_path / "all_text_main.duckdb")
    headers = ["whole", "decimal", "fixed", "datetime", "date", "text", "bool", "exotic"]
    rows_text = [
        ["100", "1.5", "99.99", "2026-11-23T11:30:45", "2026-01-15", "Apple", "True", " 12 "],
        ["-50", "-0.5", "-123.45", "2025-05-10 08:00:00", "2025-05-10", "banana", "false", "1_000"],
        ["0", "2.25", "0.00", "2000-01-01T00:00:00", "2000-01-01", "ORANGE", "TRUE", "1e3"],
        ["999999999999", "240", "1000.00", "2099-12-31T23:59:59", "2099-12-31", "Grape", "False", "+5"],
        ["", "", "", "", "", "", "", ".5"],
        [None, None, None, None, None, None, None, "5."],
        ["20", "1.50", "50.00", "2026-11-23T11:30:45", "2026-11-23", "café", "true", "plain"],
    ]
    dict_rows = [dict(zip(headers, r)) for r in rows_text]
    col_types = infer_column_types(headers, dict_rows)

    cols = [(h, "text") for h in headers]
    with DuckStore(db_path) as store:
        store.create_table("all_text", cols)
        store.append_rows("all_text", [tuple(r) for r in rows_text])

        csv_m = CsvTableModel()
        store_m = StoreTableModel(store)

        csv_m.replace_data(headers, dict_rows, column_types=col_types)
        store_m.replace_data("all_text", headers, column_types=col_types)

        _assert_models_identical(csv_m, store_m, "all_text initial")

        for idx, col in enumerate(headers):
            csv_m.sortByColumn(idx)
            store_m.sortByColumn(idx)
            _assert_models_identical(csv_m, store_m, f"all_text sort asc {col}")

            csv_m.sortByColumn(idx)
            store_m.sortByColumn(idx)
            _assert_models_identical(csv_m, store_m, f"all_text sort desc {col}")

        # Clear sort
        csv_m._sort_column = ""
        csv_m._apply_sort()
        csv_m._update_page_rows()
        store_m._sort_column = ""
        store_m._materialize_state()
        store_m._load_page_rows()

        filter_tests = [
            ("whole", "equals", "100"),
            ("whole", "not_equals", "100"),
            ("whole", "greater_than", "0"),
            ("whole", "is_null", ""),
            ("whole", "is_not_null", ""),
            ("decimal", "greater_than", "1.0"),
            ("decimal", "less_than", "2.0"),
            ("fixed", "greater_than", "0"),
            ("datetime", "contains", "11:30"),
            ("date", "equals", "2026-01-15"),
            ("text", "contains", "an"),
            ("bool", "equals", "true"),
            ("exotic", "equals", " 12 "),
            ("exotic", "contains", "1"),
        ]
        for col, op, val in filter_tests:
            csv_m.setColumnFilter(col, op, val)
            store_m.setColumnFilter(col, op, val)
            _assert_models_identical(csv_m, store_m, f"all_text filter {col} {op} {val}")

def test_fuzz_500_seeded_combinations_on_5k_tables(tmp_path, qapp):
    """500 random (data, sort, filter) combinations on 5,000-row tables for typed & all-text stores."""
    rng = random.Random(42)
    db_path = str(tmp_path / "fuzz5k.duckdb")

    with DuckStore(db_path) as store:
        # 1. Typed store
        cols_typed = [
            ("w", "whole"),
            ("d", "decimal"),
            ("dt", "datetime"),
            ("da", "datetime"),
            ("s", "text"),
            ("b", "boolean"),
        ]
        types_typed = {
            "w": "whole_number",
            "d": "decimal_number",
            "dt": "datetime",
            "da": "date",
            "s": "text",
            "b": "boolean",
        }
        store.create_table("fuzz_typed_5k", cols_typed)
        raw_rows = []
        for i in range(5000):
            raw_rows.append((
                rng.randint(-1000, 1000) if rng.random() > 0.05 else None,
                round(rng.uniform(-500, 500), 2) if rng.random() > 0.05 else None,
                datetime.datetime(2026, 5, rng.randint(1, 28), rng.randint(0, 23), 0, 0) if rng.random() > 0.05 else None,
                datetime.datetime(2026, 5, rng.randint(1, 28), 0, 0, 0) if rng.random() > 0.05 else None,
                rng.choice(["Apple", "banana", "CHERRY", "date", "", "123"]) if rng.random() > 0.05 else None,
                rng.choice([True, False]) if rng.random() > 0.05 else None,
            ))
        store.append_rows("fuzz_typed_5k", raw_rows)
        headers_typed = [c[0] for c in cols_typed]
        dict_rows_typed = []
        for r in raw_rows:
            d = dict(zip(headers_typed, r))
            if d["da"] is not None:
                d["da"] = d["da"].date()
            dict_rows_typed.append(d)

        cm_t = CsvTableModel()
        sm_t = StoreTableModel(store)
        cm_t.replace_data(headers_typed, dict_rows_typed, column_types=types_typed)
        sm_t.replace_data("fuzz_typed_5k", headers_typed, column_types=types_typed)

        for _ in range(250):
            act = rng.choice(["sort", "filter", "page"])
            if act == "sort":
                c = rng.randint(0, len(headers_typed) - 1)
                cm_t.sortByColumn(c)
                sm_t.sortByColumn(c)
            elif act == "filter":
                col = rng.choice(headers_typed)
                t = types_typed[col]
                if t == "whole_number":
                    cm_t.setColumnFilter(col, "greater_than", "0")
                    sm_t.setColumnFilter(col, "greater_than", "0")
                elif t == "text":
                    cm_t.setColumnFilter(col, "contains", "a")
                    sm_t.setColumnFilter(col, "contains", "a")
                else:
                    cm_t.setColumnFilter(col, "is_not_null", "")
                    sm_t.setColumnFilter(col, "is_not_null", "")
            elif act == "page":
                if cm_t.canGoNext:
                    cm_t.nextPage()
                    sm_t.nextPage()
                elif cm_t.canGoPrevious:
                    cm_t.previousPage()
                    sm_t.previousPage()
            assert cm_t.rowCount() == sm_t.rowCount()
            assert cm_t.currentPage == sm_t.currentPage
            for r in range(min(3, cm_t.rowCount())):
                for c in range(len(headers_typed)):
                    assert cm_t.data(cm_t.index(r, c)) == sm_t.data(sm_t.index(r, c))

        # 2. All-text store
        cols_text = [
            ("w", "text"),
            ("d", "text"),
            ("s", "text"),
            ("b", "text"),
        ]
        types_text = {
            "w": "whole_number",
            "d": "decimal_number",
            "s": "text",
            "b": "boolean",
        }
        store.create_table("fuzz_text_5k", cols_text)
        raw_text_rows = []
        for i in range(5000):
            raw_text_rows.append((
                str(rng.randint(-1000, 1000)) if rng.random() > 0.05 else None,
                str(round(rng.uniform(-500, 500), 2)) if rng.random() > 0.05 else None,
                rng.choice(["Apple", "banana", "CHERRY", "date", "", "123"]) if rng.random() > 0.05 else None,
                rng.choice(["True", "False", "true", "false"]) if rng.random() > 0.05 else None,
            ))
        store.append_rows("fuzz_text_5k", raw_text_rows)
        headers_text = [c[0] for c in cols_text]
        dict_rows_text = [dict(zip(headers_text, r)) for r in raw_text_rows]

        cm_txt = CsvTableModel()
        sm_txt = StoreTableModel(store)
        cm_txt.replace_data(headers_text, dict_rows_text, column_types=types_text)
        sm_txt.replace_data("fuzz_text_5k", headers_text, column_types=types_text)

        for _ in range(250):
            act = rng.choice(["sort", "filter", "page"])
            if act == "sort":
                c = rng.randint(0, len(headers_text) - 1)
                cm_txt.sortByColumn(c)
                sm_txt.sortByColumn(c)
            elif act == "filter":
                col = rng.choice(headers_text)
                t = types_text[col]
                if t == "whole_number":
                    cm_txt.setColumnFilter(col, "greater_than", "0")
                    sm_txt.setColumnFilter(col, "greater_than", "0")
                elif t == "text":
                    cm_txt.setColumnFilter(col, "contains", "a")
                    sm_txt.setColumnFilter(col, "contains", "a")
                else:
                    cm_txt.setColumnFilter(col, "is_not_null", "")
                    sm_txt.setColumnFilter(col, "is_not_null", "")
            elif act == "page":
                if cm_txt.canGoNext:
                    cm_txt.nextPage()
                    sm_txt.nextPage()
                elif cm_txt.canGoPrevious:
                    cm_txt.previousPage()
                    sm_txt.previousPage()
            assert cm_txt.rowCount() == sm_txt.rowCount()
            assert cm_txt.currentPage == sm_txt.currentPage
            for r in range(min(3, cm_txt.rowCount())):
                for c in range(len(headers_text)):
                    assert cm_txt.data(cm_txt.index(r, c)) == sm_txt.data(sm_txt.index(r, c))

def test_regression_blockers_and_mutations(tmp_path, qapp):
    """Explicit regression tests for B2-B15 and mutation survivors."""
    db_path = str(tmp_path / "regressions.duckdb")
    with DuckStore(db_path) as store:
        # B2: Values filter all=True with NULLs preserved
        store.create_table("t_b2", [("val", "text")])
        store.append_rows("t_b2", [("A",), ("B",), (None,)])
        cm = CsvTableModel()
        sm = StoreTableModel(store)
        cm.replace_data(["val"], [{"val": "A"}, {"val": "B"}, {"val": None}])
        sm.replace_data("t_b2", ["val"])
        
        # Exclude 'B' with all=True (values filter exclude some)
        cm.setColumnFilter("val", "values", {"all": True, "keys": {"B": False}})
        sm.setColumnFilter("val", "values", {"all": True, "keys": {"B": False}})
        _assert_models_identical(cm, sm, "B2 values filter NULL preserved")

        # B6: Temp view __stm_ naming & hidden from table_names
        assert all(t.startswith("__stm_") for t in [sm._active_view_name] if t)
        assert sm._active_view_name not in store.table_names()

        # B7 & B14: columnFilterValues truncation & ordering
        store.create_table("t_trunc", [("k", "whole")])
        store.append_rows("t_trunc", [(i,) for i in range(6000)])
        sm_tr = StoreTableModel(store)
        sm_tr.replace_data("t_trunc", ["k"])
        assert sm_tr.columnFilterValuesTruncated("k") is True
        assert sm_tr.columnFilterValueTotal("k") == 6000
        vals = sm_tr.columnFilterValues("k")
        assert len(vals["values"]) == 2000
        assert vals["values"][0]["label"] == "0"
        # Total distinct values is 6000, 2000 returned, sorted by label
        assert any(v["label"] == "1" for v in vals["values"])

        # B8: Non-ASCII text fallback
        store.create_table("t_unicode", [("txt", "text")])
        store.append_rows("t_unicode", [("CAFÉ",), ("café",), ("other",)])
        cm_u = CsvTableModel()
        sm_u = StoreTableModel(store)
        cm_u.replace_data(["txt"], [{"txt": "CAFÉ"}, {"txt": "café"}, {"txt": "other"}])
        sm_u.replace_data("t_unicode", ["txt"])
        cm_u.setColumnFilter("txt", "contains", "café")
        sm_u.setColumnFilter("txt", "contains", "café")
        _assert_models_identical(cm_u, sm_u, "B8 unicode casefold")

        # B9: Case-sensitive values filter
        cm_u.setColumnFilter("txt", "values", {"all": False, "keys": {"café": True}})
        sm_u.setColumnFilter("txt", "values", {"all": False, "keys": {"café": True}})
        _assert_models_identical(cm_u, sm_u, "B9 case-sensitive values")

        # Mutation: LIKE escaping %, _, \
        store.create_table("t_like", [("txt", "text")])
        store.append_rows("t_like", [("100%",), ("100_abc",), ("100\\abc",), ("1000",)])
        cm_l = CsvTableModel()
        sm_l = StoreTableModel(store)
        cm_l.replace_data(["txt"], [{"txt": "100%"}, {"txt": "100_abc"}, {"txt": "100\\abc"}, {"txt": "1000"}])
        sm_l.replace_data("t_like", ["txt"])

        cm_l.setColumnFilter("txt", "contains", "%")
        sm_l.setColumnFilter("txt", "contains", "%")
        _assert_models_identical(cm_l, sm_l, "like escape %")

        cm_l.setColumnFilter("txt", "contains", "_")
        sm_l.setColumnFilter("txt", "contains", "_")
        _assert_models_identical(cm_l, sm_l, "like escape _")

        cm_l.setColumnFilter("txt", "contains", "\\")
        sm_l.setColumnFilter("txt", "contains", "\\")
        _assert_models_identical(cm_l, sm_l, "like escape \\")

        cm_l.setColumnFilter("txt", "begins_with", "100_")
        sm_l.setColumnFilter("txt", "begins_with", "100_")
        _assert_models_identical(cm_l, sm_l, "like begins_with _")

        # Mutation: page reset on sort
        store.create_table("t_pages", [("id", "whole")])
        store.append_rows("t_pages", [(i,) for i in range(1200)])
        sm_p = StoreTableModel(store)
        sm_p.replace_data("t_pages", ["id"])
        assert sm_p.currentPage == 1
        sm_p.nextPage()
        assert sm_p.currentPage == 2
        sm_p.sortByColumn(0)
        assert sm_p.currentPage == 1  # reset to page 1

        # Mutation: filter memory per table key & stale key pruning
        sm_p.replace_data("t_pages", ["id"], table_key="tbl_key_1")
        sm_p.setColumnFilter("id", "greater_than", "500")
        assert "id" in sm_p.activeFilterColumns
        # Re-replacing data with the same table key should restore filters
        sm_p.replace_data("t_pages", ["id"], table_key="tbl_key_1")
        assert "id" in sm_p.activeFilterColumns
        # Replace data without that column should prune filter
        store.create_table("t_other", [("other_col", "text")])
        store.append_rows("t_other", [("hello",)])
        sm_p.replace_data("t_other", ["other_col"], table_key="tbl_key_1")
        assert "id" not in sm_p.activeFilterColumns
