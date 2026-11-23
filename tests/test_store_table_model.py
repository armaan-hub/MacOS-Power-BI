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


# ======================================================================
# Re-review fixes (N1 to N8) and mutation-survivor tests
# ======================================================================

import pyarrow as pa
from decimal import Decimal

from PySide6.QtCore import qInstallMessageHandler

import analytics_studio.store.table_model as table_model_module
from analytics_studio.store.base import StoreError


_BUSY = "The store is busy with another operation."


def _text_pair(store, name, headers, rows, ctypes, key="k"):
    """The same all-text data in a store table and in a CsvTableModel."""
    store.create_table(name, [(h, "text") for h in headers])
    store.append_rows(name, [tuple(r) for r in rows])
    dict_rows = [dict(zip(headers, r)) for r in rows]
    cm = CsvTableModel()
    cm.replace_data(headers, dict_rows, key, ctypes)
    sm = StoreTableModel(store)
    assert sm.replace_data(name, headers, ctypes, key)
    return cm, sm


def _assert_pages_identical(cm, sm, message=""):
    """Compare page 0, page 1 and the last page of both models (cells, ranges, counts)."""
    assert cm.pageCount == sm.pageCount, message
    pages = sorted({0, 1, cm.pageCount - 1} & set(range(max(cm.pageCount, 1))))
    for p in pages:
        cm._set_page(p)
        sm._set_page(p)
        _assert_models_identical(cm, sm, f"{message} page {p}")
    cm._set_page(0)
    sm._set_page(0)


def _assert_cfv_identical(cm, sm, column, search="", message=""):
    a = cm.columnFilterValues(column, search)
    b = sm.columnFilterValues(column, search)
    assert a == b, f"cfv {column!r} {search!r}: {message}\nold={a}\nnew={b}"


def _temp_view_count(store):
    return store.execute(
        "SELECT count(*) FROM duckdb_tables() WHERE temporary AND table_name LIKE '\\_\\_stm\\_%' ESCAPE '\\'"
    )[0][0]


def _fresh_pair(cm, sm, headers, dict_rows, ctypes, key):
    cm.replace_data(headers, dict_rows, key, ctypes)
    sm.replace_data(sm._table_name, headers, ctypes, key)


# ---------------------------------------------------------------- N1


def test_n1_text_store_value_filter_keeps_raw_keys_apart(tmp_path, qapp):
    """On a text store the value keys are the raw cell strings, whatever the label says."""
    headers = ["dec", "bl", "dtm", "dat", "whole", "txt"]
    ctypes = {
        "dec": "decimal_number", "bl": "boolean", "dtm": "datetime", "dat": "date",
        "whole": "whole_number", "txt": "text",
    }
    pools = {
        "dec": ["1.5", "1.50", "0", "0.0", "00", "+0", "-0", "2", None, ""],
        "bl": ["True", "TRUE", "true", "False", "false", None, ""],
        "dtm": ["2020-01-05T10:00:00", "2020-01-05 10:00:00", "2020-01-06T00:00:00", None, ""],
        "dat": ["2020-01-05", "2020-01-06", "2020-01-05", None, ""],
        "whole": ["7", "07", "+7", "8", "-0", "0", None, ""],
        "txt": ["a", "A", "b", "B", None, ""],
    }
    rng = random.Random(11)
    rows = [tuple(rng.choice(pools[h]) for h in headers) for _ in range(120)]
    with DuckStore(str(tmp_path / "n1.duckdb")) as store:
        cm, sm = _text_pair(store, "t", headers, rows, ctypes)
        for col in headers:
            _assert_cfv_identical(cm, sm, col, message="keys")
            values = cm.columnFilterValues(col, "")["values"]
            assert len(values) >= 3
            for v in values:
                for all_selected in (False, True):
                    cm.replace_data(headers, [dict(zip(headers, r)) for r in rows], "n1", ctypes)
                    sm.replace_data("t", headers, ctypes, "n1")
                    cm.setColumnValueFilter(col, all_selected, [v["key"]])
                    sm.setColumnValueFilter(col, all_selected, [v["key"]])
                    _assert_pages_identical(
                        cm, sm, f"n1 {col} key {v['label']!r} all={all_selected}"
                    )
        # The reviewer's cases, spelled out: one key keeps '1.50' and '0.0' out.
        cm.replace_data(headers, [dict(zip(headers, r)) for r in rows], "n1b", ctypes)
        sm.replace_data("t", headers, ctypes, "n1b")
        key = [v["key"] for v in cm.columnFilterValues("dec", "")["values"] if v["label"] == "1.5"]
        sm.setColumnValueFilter("dec", False, key)
        shown = {sm.data(sm.index(r, 0)) for r in range(sm.rowCount())}
        assert shown == {"1.5"}
        key = [v["key"] for v in cm.columnFilterValues("bl", "")["values"] if v["label"] == "TRUE"]
        sm.clearColumnFilter("dec")
        sm.setColumnValueFilter("bl", False, key)
        assert {sm.data(sm.index(r, 1)) for r in range(sm.rowCount())} == {"TRUE"}


def test_n1_text_store_value_filter_is_case_sensitive_and_blank_aware(tmp_path, qapp):
    """'a' and 'A' are different keys (no NOCASE) and NULL stays visible when others are excluded."""
    headers = ["txt", "num"]
    ctypes = {"txt": "text", "num": "whole_number"}
    rows = [("a", "1"), ("A", "2"), ("b", None), (None, "3"), ("", "")] * 4
    with DuckStore(str(tmp_path / "n1case.duckdb")) as store:
        cm, sm = _text_pair(store, "t", headers, rows, ctypes)
        for col in headers:
            for v in cm.columnFilterValues(col, "")["values"]:
                for all_selected in (False, True):
                    _fresh_pair(cm, sm, headers, [dict(zip(headers, r)) for r in rows], ctypes, "c")
                    cm.setColumnValueFilter(col, all_selected, [v["key"]])
                    sm.setColumnValueFilter(col, all_selected, [v["key"]])
                    _assert_pages_identical(cm, sm, f"case {col} {v['label']!r} all={all_selected}")
        _fresh_pair(cm, sm, headers, [dict(zip(headers, r)) for r in rows], ctypes, "c2")
        key_a = [v["key"] for v in cm.columnFilterValues("txt", "")["values"] if v["label"] == "a"]
        sm.setColumnValueFilter("txt", False, key_a)
        assert {sm.data(sm.index(r, 0)) for r in range(sm.rowCount())} == {"a"}
        sm.setColumnValueFilter("txt", True, key_a)
        shown = [sm.data(sm.index(r, 0)) for r in range(sm.rowCount())]
        assert "(null)" in shown and "A" in shown and "a" not in shown


def test_values_filter_all_true_keeps_null_rows_on_both_shapes(tmp_path, qapp):
    """COALESCE guard: excluding one value must keep NULL cells (text store and typed store)."""
    with DuckStore(str(tmp_path / "coalesce.duckdb")) as store:
        headers = ["w", "t"]
        ctypes = {"w": "whole_number", "t": "text"}
        rows = [(1, "x"), (2, None), (None, "y"), (3, ""), (1, "x"), (None, None)]
        store.create_table("typed", [("w", "whole"), ("t", "text")])
        store.append_rows("typed", rows)
        cm = CsvTableModel()
        cm.replace_data(headers, [dict(zip(headers, r)) for r in rows], "c", ctypes)
        sm = StoreTableModel(store)
        sm.replace_data("typed", headers, ctypes, "c")
        for col in headers:
            for v in cm.columnFilterValues(col, "")["values"]:
                cm.setColumnValueFilter(col, True, [v["key"]])
                sm.setColumnValueFilter(col, True, [v["key"]])
                _assert_pages_identical(cm, sm, f"typed {col} exclude {v['label']!r}")
                cm.clearColumnFilter(col)
                sm.clearColumnFilter(col)
        text_rows = [tuple(None if v is None else str(v) for v in r) for r in rows]
        cm2, sm2 = _text_pair(store, "texty", headers, text_rows, ctypes, "c2")
        for col in headers:
            for v in cm2.columnFilterValues(col, "")["values"]:
                cm2.setColumnValueFilter(col, True, [v["key"]])
                sm2.setColumnValueFilter(col, True, [v["key"]])
                _assert_pages_identical(cm2, sm2, f"text {col} exclude {v['label']!r}")
                cm2.clearColumnFilter(col)
                sm2.clearColumnFilter(col)
        # Excluding '1' must keep the three NULL-weight rows (explicit count).
        key_one = [v["key"] for v in cm.columnFilterValues("w", "")["values"] if v["label"] == "1"]
        sm.setColumnValueFilter("w", True, key_one)
        assert sm.pageRange == "Rows 1–4 of 4"


# ---------------------------------------------------------------- N2 / N3


class _FailAt:
    """Count the store calls the model makes and raise StoreError at the k-th one."""

    NAMES = (
        "execute", "read_page", "create_view_ids", "register_arrow_ids",
        "has_table", "columns", "row_count",
    )

    def __init__(self, store, k=None, message=_BUSY):
        self.store = store
        self.k = k
        self.calls = 0
        self.message = message
        for name in self.NAMES:
            original = getattr(store, name)

            def wrapper(*args, _orig=original, **kwargs):
                self.calls += 1
                if self.k is not None and self.calls == self.k:
                    raise StoreError(self.message)
                return _orig(*args, **kwargs)

            setattr(store, name, wrapper)

    def close(self):
        for name in self.NAMES:
            try:
                delattr(self.store, name)
            except AttributeError:
                pass


_SLOT_HEADERS = ["c", "d", "t"]
_SLOT_TYPES = {"c": "whole_number", "d": "date", "t": "text"}


def _slot_rows():
    return [
        (str(i % 7), "2020-01-%02d" % (1 + i % 9), "abc"[i % 3] + str(i % 11))
        for i in range(1300)
    ]


def _slot_setup(store, to_last_page):
    store.create_table("t", [(h, "text") for h in _SLOT_HEADERS])
    store.append_rows("t", _slot_rows())
    sm = StoreTableModel(store)
    assert sm.replace_data("t", _SLOT_HEADERS, _SLOT_TYPES, "k")
    sm.sortByColumn(0)
    sm.setColumnFilter("d", "greater_than", "2020-01-03")
    assert sm.pageCount == 2
    if to_last_page:
        sm.nextPage()
    return sm


def _slot_state(sm):
    return {
        "range": sm.pageRange,
        "page": sm.currentPage,
        "sort": (sm.sortColumn, sm.sortDirection),
        "filters": {c: sm.columnFilter(c) for c in sm.activeFilterColumns},
        "cells": [
            tuple(sm.data(sm.index(r, c)) for c in range(sm.columnCount()))
            for r in range(sm.rowCount())
        ],
        "can": (sm.canGoPrevious, sm.canGoNext),
        "view": sm._active_view_name,
        "memory": (dict(sm._sort_by_table), dict(sm._filters_by_table)),
    }


_SLOT_ACTIONS = {
    "sort": (False, lambda sm, keys: sm.sortByColumn(2)),
    "filter": (False, lambda sm, keys: sm.setColumnFilter("t", "contains", "a")),
    "valuefilter": (False, lambda sm, keys: sm.setColumnValueFilter("c", False, keys)),
    "clear": (False, lambda sm, keys: sm.clearColumnFilter("d")),
    "replace": (False, lambda sm, keys: sm.replace_data("t", _SLOT_HEADERS, _SLOT_TYPES, "k")),
    "next": (False, lambda sm, keys: sm.nextPage()),
    "previous": (True, lambda sm, keys: sm.previousPage()),
}


@pytest.mark.parametrize("slot", sorted(_SLOT_ACTIONS))
def test_n2_failure_at_every_step_keeps_old_state_and_paging(tmp_path, qapp, slot):
    """Force a StoreError at each store call of each mutating slot: nothing may change."""
    to_last_page, action = _SLOT_ACTIONS[slot]
    messages = []
    previous_handler = qInstallMessageHandler(lambda mode, ctx, msg: messages.append(msg))
    try:
        # Count the store calls of an unforced run, on a fresh model.
        with DuckStore(str(tmp_path / f"{slot}_count.duckdb")) as store:
            sm = _slot_setup(store, to_last_page)
            keys = [v["key"] for v in sm.columnFilterValues("c", "")["values"][:2]]
            counter = _FailAt(store)
            action(sm, keys)
            counter.close()
            total_calls = counter.calls
            assert total_calls >= 1
            assert sm.lastError == ""

        for k in range(1, total_calls + 1):
            with DuckStore(str(tmp_path / f"{slot}_{k}.duckdb")) as store:
                sm = _slot_setup(store, to_last_page)
                keys = [v["key"] for v in sm.columnFilterValues("c", "")["values"][:2]]
                before = _slot_state(sm)
                views_before = _temp_view_count(store)
                errors = []
                sm.storeError.connect(errors.append)
                messages.clear()
                forced = _FailAt(store, k=k)
                try:
                    result = action(sm, keys)
                finally:
                    forced.close()
                where = f"{slot} failing at store call {k}/{total_calls}"
                if slot == "replace":
                    assert result is False, where
                assert _slot_state(sm) == before, where
                assert errors == [_BUSY], where
                assert sm.lastError == _BUSY, where
                assert _temp_view_count(store) == views_before, where
                assert not [m for m in messages if "eginResetModel" in m or "endResetModel" in m], (
                    where, messages,
                )
                # The model still pages: the old view must still exist.
                if before["can"][1]:
                    sm.nextPage()
                    assert sm.currentPage == before["page"] + 1, where
                elif before["can"][0]:
                    sm.previousPage()
                    assert sm.currentPage == before["page"] - 1, where
                assert sm.lastError == "", where
                assert _temp_view_count(store) == views_before, where
    finally:
        qInstallMessageHandler(previous_handler)


def test_n2_success_replaces_view_and_drops_the_old_one(tmp_path, qapp):
    with DuckStore(str(tmp_path / "n2ok.duckdb")) as store:
        sm = _slot_setup(store, False)
        old_view = sm._active_view_name
        assert old_view is not None and _temp_view_count(store) == 1
        sm.sortByColumn(2)
        assert sm._active_view_name != old_view
        assert _temp_view_count(store) == 1
        sm.clearColumnFilter("d")
        sm._sort_column = ""
        assert _temp_view_count(store) == 1
        sm.replace_data("")
        assert _temp_view_count(store) == 0


def test_n2_conversion_error_in_sql_path_retries_exactly_in_python(tmp_path, qapp):
    """A non-busy StoreError from the SQL path must not leave the sort or filter unapplied."""
    rows = _slot_rows()
    with DuckStore(str(tmp_path / "n2retry.duckdb")) as store:
        cm, sm = _text_pair(store, "t", _SLOT_HEADERS, rows, _SLOT_TYPES)
        errors = []
        sm.storeError.connect(errors.append)
        original = store.create_view_ids

        def boom(*args, **kwargs):
            raise StoreError("Conversion Error: Could not convert string 'abc' to DECIMAL")

        store.create_view_ids = boom
        try:
            cm.sortByColumn(0)
            sm.sortByColumn(0)
            cm.setColumnFilter("d", "greater_than", "2020-01-03")
            sm.setColumnFilter("d", "greater_than", "2020-01-03")
            cm.setColumnFilter("t", "contains", "a")
            sm.setColumnFilter("t", "contains", "a")
        finally:
            store.create_view_ids = original
        assert errors == []
        assert sm.lastError == ""
        _assert_pages_identical(cm, sm, "retry on python path")

        # A busy store is not retried: the change is refused and reported once.
        def busy(*args, **kwargs):
            raise StoreError(_BUSY)

        before = _slot_state(sm)
        store.create_view_ids = busy
        try:
            sm.sortByColumn(1)
        finally:
            store.create_view_ids = original
        assert errors == [_BUSY]
        assert _slot_state(sm) == before


def test_n3_every_slot_survives_a_real_busy_import(tmp_path, qapp):
    """setColumnValueFilter (and every other slot) must not raise while an import holds the store."""
    messages = []
    previous_handler = qInstallMessageHandler(lambda mode, ctx, msg: messages.append(msg))
    started, release = threading.Event(), threading.Event()
    outcome = {}

    def batches():
        started.set()
        release.wait(30)
        yield pa.record_batch([pa.array(["x"], type=pa.string())], names=["a"])

    try:
        with DuckStore(str(tmp_path / "n3.duckdb")) as store:
            sm = _slot_setup(store, False)
            errors = []
            sm.storeError.connect(errors.append)
            before = _slot_state(sm)
            thread = threading.Thread(
                target=lambda: outcome.update(
                    rows=store.create_table_from_arrow("imp", [("a", "text")], batches())
                )
            )
            thread.start()
            try:
                assert started.wait(15)
                calls = {
                    "sort": lambda: sm.sortByColumn(1),
                    "filter": lambda: sm.setColumnFilter("c", "equals", "1"),
                    "valuefilter": lambda: sm.setColumnValueFilter("c", False, ["x"]),
                    "valuefilter_all": lambda: sm.setColumnValueFilter("c", True, ["x"]),
                    "clear": lambda: sm.clearColumnFilter("d"),
                    "next": lambda: sm.nextPage(),
                }
                for name, call in calls.items():
                    before_count = len(errors)
                    try:
                        call()
                    except BaseException as exc:  # noqa: BLE001
                        pytest.fail(f"{name} raised {exc!r} while the store was busy")
                    assert len(errors) == before_count + 1, name
                    assert _slot_state(sm) == before, name
                assert sm.replace_data("t", _SLOT_HEADERS, _SLOT_TYPES, "k") is False
                assert _slot_state(sm) == before
                neutral = sm.columnFilterValues("c", "")
                assert neutral["values"] == [] and neutral["matchCount"] == 0
                assert sm.columnFilterValueTotal("c") == 0
                assert sm.columnFilterValuesTruncated("c") is False
                assert not [m for m in messages if "eginResetModel" in m or "endResetModel" in m]
            finally:
                release.set()
                thread.join(30)
            assert outcome.get("rows") == 1
            errors.clear()
            sm.sortByColumn(1)
            assert errors == [] and sm.lastError == ""
            assert sm.sortColumn == "d"
    finally:
        release.set()
        qInstallMessageHandler(previous_handler)


# ---------------------------------------------------------------- N4


def _sort_and_filter_compare(store, name, label, cells, filters, extra_headers=True):
    headers = ["c", "i"]
    rows = [(cell, str(i)) for i, cell in enumerate(cells)]
    ctypes = {"c": label, "i": "text"}
    cm, sm = _text_pair(store, name, headers, rows, ctypes, name)
    for _ in range(2):
        cm.sortByColumn(0)
        sm.sortByColumn(0)
        _assert_pages_identical(cm, sm, f"{name} sort {sm.sortDirection}")
    cm.sortByColumn(1)
    sm.sortByColumn(1)
    for operator, value in filters:
        _fresh_pair(cm, sm, headers, [dict(zip(headers, r)) for r in rows], ctypes, f"{name}-{operator}")
        cm.setColumnFilter("c", operator, value)
        sm.setColumnFilter("c", operator, value)
        _assert_pages_identical(cm, sm, f"{name} filter {operator} {value!r}")
        cm.sortByColumn(0)
        sm.sortByColumn(0)
        _assert_pages_identical(cm, sm, f"{name} filter {operator} {value!r} then sort")
    return cm, sm


_ORDER_AND_EQ = ("equals", "not_equals", "greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal")


def test_n4_whole_number_label_with_non_integer_cells_and_expected(tmp_path, qapp):
    cells = ["3", "10", "1.5", "2", None, "", "-4", "1.0", "007", "+9"]
    filters = [(op, v) for op in _ORDER_AND_EQ for v in ("2", "1.5", "1.0", "abc", "")]
    with DuckStore(str(tmp_path / "n4whole.duckdb")) as store:
        _, sm = _sort_and_filter_compare(store, "w", "whole_number", cells, filters)
        assert sm._check_canonical("c") is False


def test_n4_non_integer_expected_value_on_integer_columns_typed_and_text(tmp_path, qapp):
    """whole_number with expected '1.5': the old model compares as text (greater_than gives No rows)."""
    ints = list(range(-5, 6)) * 3
    rows_text = [(str(v), str(i)) for i, v in enumerate(ints)]
    headers = ["c", "i"]
    ctypes = {"c": "whole_number", "i": "text"}
    with DuckStore(str(tmp_path / "n4typed.duckdb")) as store:
        store.create_table("typed", [("c", "whole"), ("i", "text")])
        store.append_rows("typed", [(v, str(i)) for i, v in enumerate(ints)])
        cm_t = CsvTableModel()
        cm_t.replace_data(headers, [{"c": v, "i": str(i)} for i, v in enumerate(ints)], "t", ctypes)
        sm_t = StoreTableModel(store)
        sm_t.replace_data("typed", headers, ctypes, "t")
        cm_x, sm_x = _text_pair(store, "texty", headers, rows_text, ctypes, "x")
        for cm, sm, tag in ((cm_t, sm_t, "typed"), (cm_x, sm_x, "text")):
            for op in _ORDER_AND_EQ:
                for value in ("1.5", "1.0", "-2.5", "3", "1e1", " 3 "):
                    cm.setColumnFilter("c", op, value)
                    sm.setColumnFilter("c", op, value)
                    _assert_pages_identical(cm, sm, f"{tag} {op} {value!r}")
            cm.setColumnFilter("c", "greater_than", "1.5")
            sm.setColumnFilter("c", "greater_than", "1.5")
            assert sm.pageRange == cm.pageRange == "No rows"


def test_n4_invalid_calendar_dates_go_to_the_python_path(tmp_path, qapp):
    cells = [
        "2020-02-29", "2020-02-30", "2020-13-01", "0000-01-01", "2021-02-29", "2019-12-31",
        "2020-01-05", None, "", "2020-00-10", "2020-01-00", "9999-12-31", "0001-01-01",
    ]
    filters = [(op, v) for op in _ORDER_AND_EQ for v in ("2020-01-05", "2020-02-30", "0000-01-01", "2021-02-29")]
    filters += [("contains", "-02-"), ("begins_with", "2020"), ("is_blank", ""), ("is_not_null", "")]
    with DuckStore(str(tmp_path / "n4date.duckdb")) as store:
        _, sm = _sort_and_filter_compare(store, "d", "date", cells, filters)
        assert sm._check_canonical("c") is False


def test_n4_invalid_times_in_datetimes_go_to_the_python_path(tmp_path, qapp):
    cells = [
        "2020-01-05T10:00:00", "2020-01-05 10:00:00", "2020-01-05T24:00:00", "2020-01-05T25:00:00",
        "2020-01-05T23:59:60", "2020-01-05T23:59:59", "2020-02-30T10:00:00", "2020-01-05T10:00:00.5",
        "2020-01-05T10:00:00.123456", "0000-01-01T00:00:00", None, "", "2020-01-05T10:60:00",
    ]
    filters = [
        (op, v) for op in _ORDER_AND_EQ
        for v in ("2020-01-05T10:00:00", "2020-01-05 10:00:00", "2020-01-05", "2020-01-05T24:00:00", "2020-02-30T00:00:00")
    ]
    with DuckStore(str(tmp_path / "n4dt.duckdb")) as store:
        _, sm = _sort_and_filter_compare(store, "dt", "datetime", cells, filters)
        assert sm._check_canonical("c") is False


def test_n4_filter_text_that_sql_casts_but_the_old_parse_treats_differently(tmp_path, qapp):
    """'20200105' and ISO week text parse in Python 3.11+ and DuckDB casts differ: stay exact."""
    cells = ["2020-01-05", "2020-01-06", "2019-12-29", "2019-12-30", "2020-01-01", None, ""]
    filters = [
        (op, v) for op in _ORDER_AND_EQ
        for v in ("20200105", "2020-W01-1", "2020-01-05T00:00:00", "2020-1-5", "2020-01-05", " 2020-01-05")
    ]
    with DuckStore(str(tmp_path / "n4txt.duckdb")) as store:
        _sort_and_filter_compare(store, "d", "date", cells, filters)
        cells_dt = ["2020-01-05T10:00:00", "2020-01-05 00:00:00", "2019-12-30T00:00:00", None, ""]
        filters_dt = [
            (op, v) for op in _ORDER_AND_EQ
            for v in ("20200105T100000", "2020-W01-1", "2020-01-05T10:00:00Z", "2020-01-05T10:00:00+04:00", "2020-01-05")
        ]
        _sort_and_filter_compare(store, "dt", "datetime", cells_dt, filters_dt)


@pytest.mark.parametrize(
    "label,bad_cell",
    [
        ("whole_number", "1.5"), ("whole_number", " 12"), ("whole_number", "1e3"),
        ("whole_number", "1_000"), ("whole_number", "+"), ("whole_number", "1234567890123456789"),
        ("decimal_number", " 1.5"), ("decimal_number", "1e3"), ("decimal_number", "1_000"),
        ("decimal_number", ".5"), ("decimal_number", "5."), ("decimal_number", "NaN"),
        ("decimal_number", "1.5 "), ("decimal_number", "1,5"),
        ("boolean", " true"), ("boolean", "yes"), ("boolean", "1"), ("boolean", "truee"),
        ("date", "2020-02-30"), ("date", "2020-1-5"), ("date", "0000-01-01"), ("date", "20200105"),
        ("date", "2020-01-05T00:00:00"), ("date", " 2020-01-05"),
        ("datetime", "2020-01-05T24:00:00"), ("datetime", "2020-01-05T10:00:00Z"),
        ("datetime", "2020-01-05T10:00:00+04:00"), ("datetime", "2020-01-05T23:59:60"),
        ("datetime", "2020-02-30T10:00:00"), ("datetime", "2020-01-05T10:00"),
        ("datetime", "2020-01-05T10:00:00.1234567"),
    ],
)
def test_n4_canonical_check_is_at_least_as_strict_as_the_old_parse(tmp_path, qapp, label, bad_cell):
    good = {
        "whole_number": ["12", "-3", "+7", "0"], "decimal_number": ["1.5", "-0.25", "100", "+3.0"],
        "boolean": ["true", "FALSE", "True"], "date": ["2020-01-05", "2020-02-29"],
        "datetime": ["2020-01-05T10:00:00", "2020-01-05 10:00:00.5", "2020-02-29 23:59:59"],
    }[label]
    with DuckStore(str(tmp_path / "canon.duckdb")) as store:
        ctypes = {"c": label}
        cm, sm = _text_pair(store, "good", ["c"], [(v,) for v in good + ["", None]], ctypes)
        assert sm._check_canonical("c") is True
        cm2, sm2 = _text_pair(store, "bad", ["c"], [(v,) for v in good + [bad_cell]], ctypes, "k2")
        assert sm2._check_canonical("c") is False
        for _ in range(2):
            cm2.sortByColumn(0)
            sm2.sortByColumn(0)
            _assert_pages_identical(cm2, sm2, f"{label} {bad_cell!r} sort")
        cm2.setColumnFilter("c", "greater_than", good[0])
        sm2.setColumnFilter("c", "greater_than", good[0])
        _assert_pages_identical(cm2, sm2, f"{label} {bad_cell!r} filter")


# ---------------------------------------------------------------- N5


def test_n5_date_label_on_text_store_shows_and_keys_raw_text(tmp_path, qapp):
    cells = ["20200105", "2020-W01-1", "2020-01-05", "2019-12-30", None, "", "2020-01-05"]
    headers = ["d", "i"]
    ctypes = {"d": "date", "i": "text"}
    rows = [(c, str(i)) for i, c in enumerate(cells)]
    with DuckStore(str(tmp_path / "n5.duckdb")) as store:
        cm, sm = _text_pair(store, "t", headers, rows, ctypes)
        _assert_pages_identical(cm, sm, "raw date text display")
        shown = [sm.data(sm.index(r, 0)) for r in range(sm.rowCount())]
        assert shown[:2] == ["20200105", "2020-W01-1"]
        _assert_cfv_identical(cm, sm, "d")
        for v in cm.columnFilterValues("d", "")["values"]:
            for all_selected in (False, True):
                _fresh_pair(cm, sm, headers, [dict(zip(headers, r)) for r in rows], ctypes, "n5")
                cm.setColumnValueFilter("d", all_selected, [v["key"]])
                sm.setColumnValueFilter("d", all_selected, [v["key"]])
                _assert_pages_identical(cm, sm, f"n5 values {v['label']!r} all={all_selected}")
        for op in ("contains", "begins_with", "equals", "greater_than"):
            for value in ("2020", "20200105", "2020-01-05", "-W"):
                _fresh_pair(cm, sm, headers, [dict(zip(headers, r)) for r in rows], ctypes, "n5f")
                cm.setColumnFilter("d", op, value)
                sm.setColumnFilter("d", op, value)
                _assert_pages_identical(cm, sm, f"n5 {op} {value}")


def test_n5_date_label_on_timestamp_store_column_shows_dates(tmp_path, qapp):
    stamps = [
        datetime.datetime(2020, 1, 5, 0, 0), datetime.datetime(2020, 1, 5, 13, 30),
        datetime.datetime(2020, 1, 6, 0, 0), None, datetime.datetime(2019, 12, 31, 23, 59, 59),
    ]
    headers = ["d", "i"]
    ctypes = {"d": "date", "i": "text"}
    with DuckStore(str(tmp_path / "n5t.duckdb")) as store:
        store.create_table("t", [("d", "datetime"), ("i", "text")])
        store.append_rows("t", [(s, str(n)) for n, s in enumerate(stamps)])
        cm = CsvTableModel()
        cm.replace_data(
            headers,
            [{"d": None if s is None else s.date(), "i": str(n)} for n, s in enumerate(stamps)],
            "k", ctypes,
        )
        sm = StoreTableModel(store)
        sm.replace_data("t", headers, ctypes, "k")
        _assert_pages_identical(cm, sm, "date label on timestamps")
        assert sm.data(sm.index(1, 0)) == "2020-01-05"
        _assert_cfv_identical(cm, sm, "d")
        for v in cm.columnFilterValues("d", "")["values"]:
            cm.setColumnValueFilter("d", False, [v["key"]])
            sm.setColumnValueFilter("d", False, [v["key"]])
            _assert_pages_identical(cm, sm, f"timestamp date key {v['label']!r}")
            cm.clearColumnFilter("d")
            sm.clearColumnFilter("d")


# ---------------------------------------------------------------- N6


def test_n6_appended_non_canonical_row_never_leaves_a_stale_cache(tmp_path, qapp):
    headers = ["c", "d"]
    ctypes = {"c": "whole_number", "d": "date"}
    rows = [(str(i % 7), "2020-01-%02d" % (1 + i % 9)) for i in range(800)]
    with DuckStore(str(tmp_path / "n6.duckdb")) as store:
        cm, sm = _text_pair(store, "t", headers, rows, ctypes)
        other = StoreTableModel(store)
        other.replace_data("t", headers, ctypes, "other")
        sm.sortByColumn(0)
        assert sm._check_canonical("c") is True and sm._check_canonical("d") is True
        assert other._check_canonical("c") is True and other._check_canonical("d") is True

        added = [("abc", "2020-02-30"), ("5", "garbage")]
        store.append_rows("t", added)
        dict_rows = [dict(zip(headers, r)) for r in rows + added]

        # Model 1 sorts again (now descending) and then filters; nothing was replaced.
        ref1 = CsvTableModel()
        ref1.replace_data(headers, dict_rows, "r1", ctypes)
        ref1.sortByColumn(0)
        ref1.sortByColumn(0)
        sm.sortByColumn(0)
        _assert_pages_identical(ref1, sm, "after append: sort again")
        assert sm.lastError == ""
        ref1.setColumnFilter("d", "greater_than", "2020-01-03")
        sm.setColumnFilter("d", "greater_than", "2020-01-03")
        _assert_pages_identical(ref1, sm, "after append: filter")
        assert sm.lastError == ""

        # A second model on the same store sees the same change token and also stays exact.
        ref2 = CsvTableModel()
        ref2.replace_data(headers, dict_rows, "r2", ctypes)
        ref2.sortByColumn(0)
        other.sortByColumn(0)
        _assert_pages_identical(ref2, other, "second model: sort")
        ref2.setColumnFilter("c", "greater_than", "2")
        other.setColumnFilter("c", "greater_than", "2")
        _assert_pages_identical(ref2, other, "second model: filter")
        assert other.lastError == ""
        assert sm._check_canonical("c") is False and other._check_canonical("d") is False


# ---------------------------------------------------------------- N7 / N8


def _single_text_column(store, name, values, label="text"):
    store.create_table(name, [("v", "text")])
    store.append_rows(name, [(v,) for v in values])
    cm = CsvTableModel()
    cm.replace_data(["v"], [{"v": v} for v in values], "k", {"v": label})
    sm = StoreTableModel(store)
    sm.replace_data(name, ["v"], {"v": label}, "k")
    return cm, sm


@pytest.mark.parametrize("distinct", [1999, 2000, 2001, 4999, 5000])
def test_n7_up_to_5000_distinct_values_is_exactly_the_old_answer(tmp_path, qapp, distinct):
    values = [f"VAL{i:05d}" for i in range(distinct)]
    values = values + values[:300]
    with DuckStore(str(tmp_path / f"cfv{distinct}.duckdb")) as store:
        cm, sm = _single_text_column(store, "t", values)
        for search in ("", "val0010", "VAL04540", "L0199", "nomatch", " 00 "):
            _assert_cfv_identical(cm, sm, "v", search, f"{distinct} distinct")
        result = sm.columnFilterValues("v", "")
        assert result["truncated"] is (distinct > 2000)
        assert result["totalCount"] == distinct
        assert len(result["values"]) == min(distinct, 2000)
        assert "matchCountCapped" not in result
        assert sm.columnFilterValueTotal("v") == distinct
        assert sm.columnFilterValuesTruncated("v") is (distinct > 2000)


def test_n7_above_5000_distinct_values_search_covers_all_values(tmp_path, qapp):
    values = [f"VAL{i:05d}" for i in range(5001)]
    values = values + values[:100]
    with DuckStore(str(tmp_path / "cfv5001.duckdb")) as store:
        cm, sm = _single_text_column(store, "t", values)
        hit = sm.columnFilterValues("v", "VAL04540")
        assert [v["label"] for v in hit["values"]] == ["VAL04540"]
        assert hit["matchCount"] == 1 and hit["truncated"] is False
        assert hit["totalCount"] == 5001 and hit["matchCountCapped"] is False
        # lower and upper case, and a match spread over many values
        assert sm.columnFilterValues("v", "val04540")["matchCount"] == 1
        many = sm.columnFilterValues("v", "VAL04")
        assert many["matchCount"] == 1000 and len(many["values"]) == 1000
        assert many["truncated"] is False and many["totalCount"] == 5001
        # nothing matches
        none = sm.columnFilterValues("v", "zzz")
        assert none["values"] == [] and none["matchCount"] == 0 and none["totalCount"] == 5001
        # no search: the first 2,000 values in first-appearance order
        everything = sm.columnFilterValues("v", "")
        assert everything["truncated"] is True and everything["matchCount"] == 5001
        assert everything["totalCount"] == 5001
        assert {v["label"] for v in everything["values"]} == {f"VAL{i:05d}" for i in range(2000)}
        # a search with more than 2,000 matches
        wide = sm.columnFilterValues("v", "val")
        assert wide["matchCount"] == 5001 and len(wide["values"]) == 2000 and wide["truncated"] is True
        # wildcard characters in the search are literal
        assert sm.columnFilterValues("v", "%")["matchCount"] == 0
        assert sm.columnFilterValues("v", "_")["matchCount"] == 0
        assert sm.columnFilterValueTotal("v") == 5001
        assert sm.columnFilterValuesTruncated("v") is True


def test_n7_large_domain_exact_python_search_for_non_ascii_and_typed_columns(tmp_path, monkeypatch, qapp):
    monkeypatch.setattr(table_model_module, "_CFV_PY_CHUNK", 777)
    values = [f"Straße{i:05d}" if i % 2 else f"STRASSE{i:05d}" for i in range(5400)]
    with DuckStore(str(tmp_path / "cfvpy.duckdb")) as store:
        cm, sm = _single_text_column(store, "t", values)
        # casefold('Straße') == 'strasse': only the exact Python path sees that
        hit = sm.columnFilterValues("v", "strasse0123")
        assert hit["matchCount"] == 10 and len(hit["values"]) == 10
        assert {v["label"] for v in hit["values"]} == {
            (f"Straße{i:05d}" if i % 2 else f"STRASSE{i:05d}") for i in range(1230, 1240)
        }
        old = cm.columnFilterValues("v", "strasse0123")
        assert {v["label"] for v in old["values"]} == {v["label"] for v in hit["values"]}
        assert hit["totalCount"] == 5400
        assert sm.columnFilterValues("v", "zzz")["matchCount"] == 0
        # a whole-number typed column above 5,000 distinct values
        store.create_table("nums", [("n", "whole")])
        store.append_rows("nums", [(i * 3,) for i in range(5600)])
        sm2 = StoreTableModel(store)
        sm2.replace_data("nums", None, {"n": "whole_number"}, "n")
        cm2 = CsvTableModel()
        cm2.replace_data(["n"], [{"n": i * 3} for i in range(5600)], "n", {"n": "whole_number"})
        got = sm2.columnFilterValues("n", "1668")
        want = [v for v in cm2.columnFilterValues("n", "1668")["values"]]
        assert got["matchCount"] == len(want)
        assert {v["label"] for v in got["values"]} == {v["label"] for v in want}
        assert got["totalCount"] == 5600


def test_n7_match_count_is_capped_and_python_search_stops_at_the_cap(tmp_path, monkeypatch, qapp):
    monkeypatch.setattr(table_model_module, "_CFV_COUNT_CAP", 150)
    values = [f"id{i:05d}" for i in range(5400)]
    with DuckStore(str(tmp_path / "cfvcap.duckdb")) as store:
        cm, sm = _single_text_column(store, "t", values)
        capped = sm.columnFilterValues("v", "id0")
        assert capped["matchCount"] == 150 and capped["matchCountCapped"] is True
        assert capped["truncated"] is True and capped["totalCount"] == 5400
        under = sm.columnFilterValues("v", "id052")
        assert under["matchCount"] == 100 and under["matchCountCapped"] is False
        # the same on the exact Python path (non-ASCII column)
        store.create_table("u", [("v", "text")])
        store.append_rows("u", [(f"é{i:05d}",) for i in range(5400)])
        sm2 = StoreTableModel(store)
        sm2.replace_data("u", ["v"], {"v": "text"}, "u")
        monkeypatch.setattr(table_model_module, "_CFV_PY_CHUNK", 100)
        capped2 = sm2.columnFilterValues("v", "é0")
        assert capped2["matchCount"] == 150 and capped2["matchCountCapped"] is True
        assert sm2.columnFilterValues("v", "é052")["matchCount"] == 100


def test_n7_large_domain_after_other_column_filter_and_date_keys(tmp_path, qapp):
    """The domain is taken after the other filters; a date label counts dates, not timestamps."""
    start = datetime.datetime(2000, 1, 1)
    stamps = [start + datetime.timedelta(hours=7 * i) for i in range(9000)]
    with DuckStore(str(tmp_path / "cfvdate.duckdb")) as store:
        store.create_table("t", [("d", "datetime"), ("g", "text")])
        store.append_rows("t", [(s, "a" if i % 2 else "b") for i, s in enumerate(stamps)])
        ctypes = {"d": "date", "g": "text"}
        cm = CsvTableModel()
        cm.replace_data(
            ["d", "g"],
            [{"d": s.date(), "g": "a" if i % 2 else "b"} for i, s in enumerate(stamps)],
            "k", ctypes,
        )
        sm = StoreTableModel(store)
        sm.replace_data("t", ["d", "g"], ctypes, "k")
        # 9000 timestamps but only about 2,625 dates: still the exact small-domain answer
        _assert_cfv_identical(cm, sm, "d")
        _assert_cfv_identical(cm, sm, "d", "2000-03")
        cm.setColumnFilter("g", "equals", "a")
        sm.setColumnFilter("g", "equals", "a")
        _assert_cfv_identical(cm, sm, "d")
        assert sm.columnFilterValueTotal("d") == cm.columnFilterValues("d", "")["totalCount"]


def test_n8_value_total_and_truncated_use_a_cache(tmp_path, qapp):
    values = [f"id{i:05d}" for i in range(6000)]
    with DuckStore(str(tmp_path / "n8cache.duckdb")) as store:
        cm, sm = _single_text_column(store, "t", values)
        assert sm.columnFilterValueTotal("v") == 6000
        assert sm.columnFilterValuesTruncated("v") is True
        # A table change makes the cached answer unreachable.
        store.append_rows("t", [(f"id{i:05d}",) for i in range(6000, 6050)])
        assert sm.columnFilterValueTotal("v") == 6050
        # Another filter on another column changes the domain, so the cache must not be reused.
        store.create_table("two", [("v", "text"), ("g", "text")])
        store.append_rows("two", [(f"id{i:05d}", "a" if i < 6001 else "b") for i in range(6100)])
        sm2 = StoreTableModel(store)
        sm2.replace_data("two", ["v", "g"], {"v": "text", "g": "text"}, "two")
        assert sm2.columnFilterValueTotal("v") == 6100
        sm2.setColumnFilter("g", "equals", "a")
        assert sm2.columnFilterValueTotal("v") == 6001
        sm2.clearColumnFilter("g")
        assert sm2.columnFilterValueTotal("v") == 6100


def test_n8_cached_totals_do_not_run_queries_again(tmp_path, qapp):
    """Second and third calls must not touch the store query methods at all."""
    values = [f"id{i:05d}" for i in range(6000)]
    with DuckStore(str(tmp_path / "n8q.duckdb")) as store:
        cm, sm = _single_text_column(store, "t", values)
        assert sm.columnFilterValueTotal("v") == 6000
        calls = []
        real_execute = store.execute
        real_read = store.read_page
        store.execute = lambda *a, **k: calls.append("execute") or real_execute(*a, **k)
        store.read_page = lambda *a, **k: calls.append("read_page") or real_read(*a, **k)
        try:
            assert sm.columnFilterValueTotal("v") == 6000
            assert sm.columnFilterValuesTruncated("v") is True
        finally:
            del store.execute
            del store.read_page
        assert calls == []


# ---------------------------------------------------------------- survivors


def test_norm_param_turns_exponent_decimals_into_plain_text(tmp_path, qapp):
    assert table_model_module._norm_param(Decimal("1E+2")) == "100"
    assert table_model_module._norm_param(Decimal("-2.4E+2")) == "-240"
    assert table_model_module._norm_param(5) == 5 and table_model_module._norm_param("x") == "x"
    # And the model applies it to every parameter it binds.
    headers = ["n"]
    with DuckStore(str(tmp_path / "norm.duckdb")) as store:
        store.create_table("t", [("n", "whole")])
        store.append_rows("t", [(v,) for v in (1, 100, 240, 100, 5)])
        sm = StoreTableModel(store)
        sm.replace_data("t", headers, {"n": "whole_number"}, "k")
        original = sm._build_filter_sql_clause
        sm._build_filter_sql_clause = lambda column, rule: (
            f'("{column}" = CAST(? AS DECIMAL(38,18)))', [Decimal("1E+2")]
        )
        try:
            sm.setColumnFilter("n", "equals", "100")
        finally:
            sm._build_filter_sql_clause = original
        assert sm.pageRange == "Rows 1–2 of 2"


def test_value_filter_keys_for_exponent_numbers_match_the_old_keys(tmp_path, qapp):
    nums = [100, 240, 1000, 5, -240, 0]
    with DuckStore(str(tmp_path / "keys.duckdb")) as store:
        store.create_table("t", [("n", "whole"), ("f", "decimal")])
        rows = [(n, float(n) / 8) for n in nums * 3]
        store.append_rows("t", rows)
        cm = CsvTableModel()
        ctypes = {"n": "whole_number", "f": "decimal_number"}
        cm.replace_data(["n", "f"], [{"n": a, "f": b} for a, b in rows], "k", ctypes)
        sm = StoreTableModel(store)
        sm.replace_data("t", ["n", "f"], ctypes, "k")
        for col in ("n", "f"):
            _assert_cfv_identical(cm, sm, col)
            for v in cm.columnFilterValues(col, "")["values"]:
                for all_selected in (False, True):
                    cm.setColumnValueFilter(col, all_selected, [v["key"]])
                    sm.setColumnValueFilter(col, all_selected, [v["key"]])
                    _assert_pages_identical(cm, sm, f"{col} {v['label']} all={all_selected}")
                    cm.clearColumnFilter(col)
                    sm.clearColumnFilter(col)


def test_non_ascii_text_falls_back_to_python_for_sort_and_filter_separately(tmp_path, qapp):
    cells = ["straße", "STRASSE", "Strasse", "É", "e", "E", "é", "İstanbul", "istanbul", "a", "B", None, ""]
    headers = ["c", "i"]
    ctypes = {"c": "text", "i": "text"}
    rows = [(c, str(i)) for i, c in enumerate(cells)]
    with DuckStore(str(tmp_path / "nonascii.duckdb")) as store:
        cm, sm = _text_pair(store, "t", headers, rows, ctypes)
        assert sm._check_non_ascii("c") is True
        # sort only
        for _ in range(2):
            cm.sortByColumn(0)
            sm.sortByColumn(0)
            _assert_pages_identical(cm, sm, "non-ascii sort")
        assert sm._build_sort_sql_clause() is None
        # filter only (sorted by the ASCII id column so the sort stays on the SQL path)
        _fresh_pair(cm, sm, headers, [dict(zip(headers, r)) for r in rows], ctypes, "na2")
        for op in ("equals", "not_equals", "contains", "begins_with", "ends_with", "greater_than", "less_than"):
            for value in ("strasse", "STRASSE", "e", "é", "istanbul", "i", "b"):
                cm.setColumnFilter("c", op, value)
                sm.setColumnFilter("c", op, value)
                _assert_pages_identical(cm, sm, f"non-ascii filter {op} {value!r}")
        assert sm._build_filter_sql_clause("c", {"operator": "contains", "value": "strasse"}) == (None, [])
        # An ASCII-only column keeps using SQL for both.
        cm2, sm2 = _text_pair(store, "ascii", headers, [("Abc", "1"), ("abd", "2")], ctypes, "k2")
        assert sm2._check_non_ascii("c") is False
        assert sm2._build_sort_sql_clause() == '"__rn" ASC'
        sm2.sortByColumn(0)
        assert sm2._build_sort_sql_clause() is not None
        assert sm2._build_filter_sql_clause("c", {"operator": "contains", "value": "ab"})[0] is not None


def test_text_operators_begin_end_contain_patterns(tmp_path, qapp):
    cells = ["abc", "cab", "xabx", "ab", "AB", "a_b", "a%b", "a\\b", "", None, "b", "ba"]
    headers = ["c"]
    ctypes = {"c": "text"}
    with DuckStore(str(tmp_path / "patterns.duckdb")) as store:
        cm, sm = _text_pair(store, "t", headers, [(c,) for c in cells], ctypes)
        for op in ("contains", "does_not_contain", "begins_with", "does_not_begin_with", "ends_with", "does_not_end_with"):
            for value in ("ab", "AB", "b", "a", "_", "%", "\\", "", "(null)", "a_", "%b"):
                cm.setColumnFilter("c", op, value)
                sm.setColumnFilter("c", op, value)
                _assert_pages_identical(cm, sm, f"pattern {op} {value!r}")
        cm.setColumnFilter("c", "begins_with", "ab")
        sm.setColumnFilter("c", "begins_with", "ab")
        assert sorted(sm.data(sm.index(r, 0)) for r in range(sm.rowCount())) == ["AB", "ab", "abc"]
        cm.setColumnFilter("c", "ends_with", "ab")
        sm.setColumnFilter("c", "ends_with", "ab")
        assert sorted(sm.data(sm.index(r, 0)) for r in range(sm.rowCount())) == ["AB", "ab", "cab"]


def test_python_path_chunk_loop_covers_every_chunk(tmp_path, monkeypatch, qapp):
    """Force the exact Python path (a ' 12 ' cell in a whole_number column) with tiny chunks."""
    for chunk in (1, 7, 21):
        monkeypatch.setattr(table_model_module, "_PY_CHUNK", chunk)
        cells = [str(i % 9) for i in range(20)] + [" 12 "]  # 21 rows: an exact multiple of 7 and 21
        headers = ["c", "i"]
        ctypes = {"c": "whole_number", "i": "text"}
        rows = [(c, str(i)) for i, c in enumerate(cells)]
        with DuckStore(str(tmp_path / f"chunk{chunk}.duckdb")) as store:
            cm, sm = _text_pair(store, "t", headers, rows, ctypes)
            assert sm._check_canonical("c") is False
            for _ in range(2):
                cm.sortByColumn(0)
                sm.sortByColumn(0)
                _assert_pages_identical(cm, sm, f"chunk {chunk} sort {sm.sortDirection}")
                assert sm.pageRange == "Rows 1–21 of 21"
            cm.setColumnFilter("c", "greater_than", "4")
            sm.setColumnFilter("c", "greater_than", "4")
            _assert_pages_identical(cm, sm, f"chunk {chunk} filter")
            assert sm.pageRange == cm.pageRange and sm.pageRange != "No rows"
        monkeypatch.undo()


def test_python_path_sort_reverses_without_losing_tie_order(tmp_path, qapp):
    cells = [" 3 ", "1", "2", "1", "3", "2", "1", None, "", " 3 "]
    headers = ["c", "i"]
    ctypes = {"c": "whole_number", "i": "text"}
    rows = [(c, str(i)) for i, c in enumerate(cells)]
    with DuckStore(str(tmp_path / "pyrev.duckdb")) as store:
        cm, sm = _text_pair(store, "t", headers, rows, ctypes)
        for _ in range(2):
            cm.sortByColumn(0)
            sm.sortByColumn(0)
            _assert_pages_identical(cm, sm, f"python sort {sm.sortDirection}")
        assert sm.sortDirection == "descending"
        ids = [sm.data(sm.index(r, 1)) for r in range(sm.rowCount())]
        # blank text sorts above numbers when reversed; equal numbers keep their row order
        assert ids == ["8", "0", "4", "9", "2", "5", "1", "3", "6", "7"]


def test_stale_value_filter_keys_are_pruned_and_empty_all_filters_dropped(tmp_path, qapp):
    headers = ["c"]
    ctypes = {"c": "text"}
    with DuckStore(str(tmp_path / "stale.duckdb")) as store:
        cm, sm = _text_pair(store, "t1", headers, [("a",), ("b",), ("c",), (None,), ("",)], ctypes, "keep")
        keys = {v["label"]: v["key"] for v in cm.columnFilterValues("c", "")["values"]}
        cm.setColumnValueFilter("c", False, [keys["a"], keys["b"], keys["c"]])
        sm.setColumnValueFilter("c", False, [keys["a"], keys["b"], keys["c"]])
        assert sm.columnFilter("c")["keys"] == cm.columnFilter("c")["keys"]
        # Replace the data: only 'b' and the null/empty cells remain.
        store.create_table("t2", [("c", "text")])
        store.append_rows("t2", [("b",), ("z",), (None,), ("",)])
        cm.replace_data(headers, [{"c": "b"}, {"c": "z"}, {"c": None}, {"c": ""}], "keep", ctypes)
        sm.replace_data("t2", headers, ctypes, "keep")
        assert sm.columnFilter("c") == cm.columnFilter("c")
        assert sm.columnFilter("c")["keys"] == [keys["b"]]
        _assert_pages_identical(cm, sm, "pruned include filter")
        # An exclude filter whose keys all vanished is dropped.
        cm.setColumnValueFilter("c", True, [keys["b"]])
        sm.setColumnValueFilter("c", True, [keys["b"]])
        store.create_table("t3", [("c", "text")])
        store.append_rows("t3", [("q",), ("r",)])
        cm.replace_data(headers, [{"c": "q"}, {"c": "r"}], "keep", ctypes)
        sm.replace_data("t3", headers, ctypes, "keep")
        assert cm.activeFilterColumns == [] and sm.activeFilterColumns == []
        assert sm.columnFilter("c") == {}
        _assert_pages_identical(cm, sm, "dropped exclude filter")
        # An include filter with no key left stays, showing nothing, like the old model.
        cm.replace_data(headers, [{"c": "b"}], "keep2", ctypes)
        sm.replace_data("t2", headers, ctypes, "keep2")
        cm.setColumnValueFilter("c", False, [keys["b"]])
        sm.setColumnValueFilter("c", False, [keys["b"]])
        cm.replace_data(headers, [{"c": "q"}], "keep2", ctypes)
        sm.replace_data("t3", headers, ctypes, "keep2")
        assert sm.columnFilter("c") == cm.columnFilter("c")
        assert sm.columnFilter("c")["keys"] == []
        _assert_pages_identical(cm, sm, "empty include filter")


def test_set_page_clamps_to_the_first_and_last_page(tmp_path, qapp):
    with DuckStore(str(tmp_path / "clamp.duckdb")) as store:
        store.create_table("t", [("n", "whole")])
        store.append_rows("t", [(i,) for i in range(1250)])
        sm = StoreTableModel(store)
        sm.replace_data("t", None, None, "k")
        assert sm.pageCount == 3
        assert sm._set_page(10**6) is True
        assert sm.currentPage == 3 and sm.rowCount() == 250
        assert sm.data(sm.index(0, 0)) == "1000" and sm.canGoNext is False
        assert sm._set_page(-5) is True
        assert sm.currentPage == 1 and sm.rowCount() == 500 and sm.data(sm.index(0, 0)) == "0"
        sm.sortByColumn(0)
        sm.sortByColumn(0)
        assert sm._set_page(99) is True
        assert sm.currentPage == 3 and sm.data(sm.index(0, 0)) == "249"


def test_decimal_store_expected_values_with_many_digits_stay_exact(tmp_path, qapp):
    """A DOUBLE column and an 18-digit expected value: SQL would round, the old model does not."""
    values = [0.1, 0.5, 12.5, 100.0, -3.25, 1e15, 1e-7, 0.30000000000000004, None]
    headers = ["d"]
    ctypes = {"d": "decimal_number"}
    with DuckStore(str(tmp_path / "dbl.duckdb")) as store:
        store.create_table("t", [("d", "decimal")])
        store.append_rows("t", [(v,) for v in values])
        cm = CsvTableModel()
        cm.replace_data(headers, [{"d": v} for v in values], "k", ctypes)
        sm = StoreTableModel(store)
        sm.replace_data("t", headers, ctypes, "k")
        for op in _ORDER_AND_EQ:
            for value in (
                "0.1", "0.100000000000000006", "0.30000000000000004", "0.3", "12.5", "12.50",
                "1000000000000000", "0.0000001", "100", "-3.25", "0.123456789012345",
            ):
                cm.setColumnFilter("d", op, value)
                sm.setColumnFilter("d", op, value)
                _assert_pages_identical(cm, sm, f"double {op} {value}")
        cm.setColumnFilter("d", "equals", "0.100000000000000006")
        sm.setColumnFilter("d", "equals", "0.100000000000000006")
        assert sm.pageRange == "No rows"
        # Text operators on a DOUBLE column see the same number text as Python (1e-07, 1e+16).
        for op in ("contains", "begins_with", "ends_with", "does_not_contain"):
            for value in ("1e", "e+", "000000", "0.0", "5", ".0", "e-07", "30000"):
                cm.setColumnFilter("d", op, value)
                sm.setColumnFilter("d", op, value)
                _assert_pages_identical(cm, sm, f"double text {op} {value}")


def test_small_domain_search_runs_no_query_after_the_first_call(tmp_path, qapp):
    values = ["Alpha", "beta", "GAMMA", "delta", None, ""] * 20
    with DuckStore(str(tmp_path / "small_cache.duckdb")) as store:
        cm, sm = _single_text_column(store, "t", values)
        _assert_cfv_identical(cm, sm, "v", "")
        calls = []
        real_execute = store.execute
        real_read = store.read_page
        store.execute = lambda *a, **k: calls.append("execute") or real_execute(*a, **k)
        store.read_page = lambda *a, **k: calls.append("read_page") or real_read(*a, **k)
        try:
            for search in ("a", "al", "alp", "GAM", "zzz", ""):
                a = cm.columnFilterValues("v", search)
                b = sm.columnFilterValues("v", search)
                assert a == b, search
        finally:
            del store.execute
            del store.read_page
        assert calls == []


def test_column_filter_value_limits_are_the_documented_ones():
    assert table_model_module._CFV_SMALL_LIMIT == 5_000
    assert table_model_module._CFV_RETURN_LIMIT == 2_000
    assert table_model_module._CFV_COUNT_CAP == 100_000
    assert table_model_module._PY_CHUNK == 50_000


def test_typed_store_keys_must_be_exactly_what_the_old_model_builds():
    """A forged key spelling can never match a cell, so it is not turned into SQL."""
    from analytics_studio.controller import _encode_data_view_filter_value as encode

    item = StoreTableModel._typed_key_item
    real = encode(Decimal("1.5"))
    assert item("number", "1.5", real, "decimal_number", "decimal") == 1.5
    assert item("number", "1.5", real, "decimal_number", "fixed") == "1.5"
    forged = encode(Decimal("1.50"))  # a different spelling of the same number
    assert forged == encode(Decimal("1.5"))  # the old encoder normalises ...
    spelled = "__npa_pqv1__:value:" + __import__("base64").urlsafe_b64encode(
        b'["number","1.50"]'
    ).decode().rstrip("=")
    assert item("number", "1.50", spelled, "decimal_number", "whole") is None
    assert item("number", "1.50", spelled, "decimal_number", "decimal") is None
    assert item("boolean", "true", "x", "boolean", "whole") is None
    assert item("number", "abc", real, "decimal_number", "whole") is None
    day = encode(datetime.date(2020, 1, 5))
    assert item("date", "2020-01-05", day, "date", "datetime") == "2020-01-05"
    assert item("date", "2020-01-05", "forged", "date", "datetime") is None
    assert item("datetime", "2020-01-05T00:00:00", day, "datetime", "datetime") is None


def test_canonical_patterns_reject_what_python_would_read_differently():
    import re

    mod = table_model_module
    ts = re.compile(mod._CANON_TS)
    assert ts.fullmatch("2020-01-05T10:00:00") and ts.fullmatch("2020-01-05 23:59:59.123456")
    for bad in ("2020-01-05T23:59:60", "2020-01-05T24:00:00", "2020-13-05T10:00:00",
                "2020-00-05T10:00:00", "2020-01-32T10:00:00", "2020-01-05T10:00", "2020-01-05T10:00:00Z",
                "2020-01-05T10:00:00.1234567", " 2020-01-05T10:00:00"):
        assert not ts.fullmatch(bad), bad
    day = re.compile(mod._CANON_DATE)
    assert day.fullmatch("2020-02-29") and not day.fullmatch("2020-1-5") and not day.fullmatch("20200105")
    assert not day.fullmatch("2020-13-01") and not day.fullmatch("2020-01-00")
    whole = re.compile(mod._CANON_INT)
    assert whole.fullmatch("-12") and not whole.fullmatch("1.0") and not whole.fullmatch(" 1")
    assert not whole.fullmatch("1" * 19)
    dec = re.compile(mod._CANON_DEC)
    assert dec.fullmatch("+1.50") and not dec.fullmatch(".5") and not dec.fullmatch("5.")
    assert not dec.fullmatch("1e3") and not dec.fullmatch("1_0")
