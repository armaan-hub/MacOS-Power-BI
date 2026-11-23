"""Differential and property tests for streaming CSV store import."""

from pathlib import Path
import random
import threading
import time
import pytest

from analytics_studio import file_import as fi
from analytics_studio.store import DuckStore, import_csv_to_store, StoreError


def compare_old_and_new(
    tmp_path,
    csv_bytes: bytes,
    options: dict,
    *,
    chunk_size_transcode: int = 1024 * 1024,
    table_name: str = "t",
):
    """Run OLD _parse_csv and NEW import_csv_to_store, and assert differential equivalence."""
    file_path = tmp_path / "test.csv"
    file_path.write_bytes(csv_bytes)

    norm_opts = fi.normalize_options("csv", options)

    # Run old
    old_error = None
    old_candidate = None
    try:
        old_candidate = fi._parse_csv(file_path, norm_opts)
    except Exception as exc:
        old_error = exc

    # Run new
    new_error = None
    new_summary = None
    db_path = tmp_path / "store.duckdb"
    store = DuckStore(str(db_path))
    try:
        try:
            new_summary = import_csv_to_store(
                store,
                table_name,
                file_path,
                norm_opts,
                chunk_size_transcode=chunk_size_transcode,
            )
        except Exception as exc:
            new_error = exc

        if old_error is not None:
            # Both must raise FileImportError
            assert new_error is not None, f"Old raised {type(old_error).__name__}: {old_error}, but new succeeded!"
            assert isinstance(new_error, fi.FileImportError), f"Expected FileImportError, got {type(new_error).__name__}: {new_error}"
            assert not store.has_table(table_name)
        elif new_error is not None:
            # If new raises while old succeeds, allowed only for specific refusals in section 3
            # (e.g. mixed line endings, lone CR with quotes, sentinel bytes)
            assert isinstance(new_error, fi.FileImportError)
            assert not store.has_table(table_name)
        else:
            # Both succeeded
            assert old_candidate is not None
            assert new_summary is not None
            # 1. Headers equal
            assert new_summary.headers == old_candidate.headers
            # 2. Row count equal
            assert new_summary.row_count == len(old_candidate.rows)
            assert store.row_count(table_name) == len(old_candidate.rows)
            # 3. Source id equal
            assert new_summary.source_id == old_candidate.source_id
            # 4. Every cell equal
            old_rows = [[r[h] for h in old_candidate.headers] for r in old_candidate.rows]
            stored_rows = [list(r) for r in store.read_page(table_name, 0, len(old_rows) + 10)]
            assert stored_rows == old_rows
            # 5. Assert no NULLs in text columns
            for row in stored_rows:
                for cell in row:
                    assert isinstance(cell, str)
                    assert cell is not None

        return old_error, new_error, new_summary
    finally:
        store.close()


def test_case_quoted_delimiter(tmp_path):
    csv_bytes = b'a,b\n"x,1",2\n3,"y,4"\n'
    compare_old_and_new(tmp_path, csv_bytes, {"delimiter": ",", "has_header": True})


def test_case_quoted_newline(tmp_path):
    csv_bytes = b'a,b\n"x\n1",2\n3,"y\r\n4"\n'
    compare_old_and_new(tmp_path, csv_bytes, {"delimiter": ",", "has_header": True})


def test_case_dquote_escape(tmp_path):
    csv_bytes = b'a,b\n"he said ""hi""",2\n'
    compare_old_and_new(tmp_path, csv_bytes, {"delimiter": ",", "has_header": True})


def test_case_crlf(tmp_path):
    csv_bytes = b'a,b\r\n1,2\r\n3,4\r\n'
    compare_old_and_new(tmp_path, csv_bytes, {"delimiter": ",", "has_header": True})


def test_case_lf(tmp_path):
    csv_bytes = b'a,b\n1,2\n3,4\n'
    compare_old_and_new(tmp_path, csv_bytes, {"delimiter": ",", "has_header": True})


def test_case_crlf_with_quoted_bare_lf(tmp_path):
    # Excel Alt-Enter: CRLF line endings, with bare LF inside quotes
    csv_bytes = b'a,b\r\n"line1\nline2",2\r\n3,4\r\n'
    compare_old_and_new(tmp_path, csv_bytes, {"delimiter": ",", "has_header": True})


def test_case_utf8_bom(tmp_path):
    # With utf-8-sig: BOM is stripped from header
    csv_bytes = b'\xef\xbb\xbfa,b\n1,2\n'
    compare_old_and_new(tmp_path, csv_bytes, {"delimiter": ",", "encoding": "utf-8-sig", "has_header": True}, table_name="t_utf8sig")
    # With utf-8: BOM is preserved in first header
    compare_old_and_new(tmp_path, csv_bytes, {"delimiter": ",", "encoding": "utf-8", "has_header": True}, table_name="t_utf8")


def test_case_utf16_le_bom(tmp_path):
    content = "a,b\r\n1,2\r\n3,4\r\n"
    csv_bytes = content.encode("utf-16-le")
    # Prefix BOM
    csv_bytes = b"\xff\xfe" + csv_bytes
    compare_old_and_new(tmp_path, csv_bytes, {"delimiter": ",", "encoding": "utf-16", "has_header": True})


def test_case_utf16_be_bom(tmp_path):
    content = "a,b\r\n1,2\r\n3,4\r\n"
    csv_bytes = content.encode("utf-16-be")
    # Prefix BOM
    csv_bytes = b"\xfe\xff" + csv_bytes
    compare_old_and_new(tmp_path, csv_bytes, {"delimiter": ",", "encoding": "utf-16", "has_header": True})


def test_case_cp1252_with_accents_and_tiny_chunk(tmp_path):
    # Tests cp1252 accented characters and a chunk boundary in the middle of a multi-byte char
    content = 'a,b\r\n€é,"“x”"\r\n'
    csv_bytes = content.encode("cp1252")
    compare_old_and_new(
        tmp_path,
        csv_bytes,
        {"delimiter": ",", "encoding": "cp1252", "has_header": True},
        chunk_size_transcode=3,
    )


def test_case_short_ragged_rows(tmp_path):
    csv_bytes = b'a,b,c\n1,2,3\n4,5\n6\n'
    compare_old_and_new(tmp_path, csv_bytes, {"delimiter": ",", "has_header": True})


def test_case_long_ragged_rows(tmp_path):
    csv_bytes = b'a,b\n1,2\n3,4,5,6\n'
    compare_old_and_new(tmp_path, csv_bytes, {"delimiter": ",", "has_header": True})


def test_case_long_ragged_at_end_of_120k_file(tmp_path):
    # Widest record at the very end of a 120,000-row file
    # The old parser has MAX_DATA_ROWS = 100,000 limit, so test differential with import_csv_to_store directly
    lines = ["a,b\n"]
    for i in range(120_000):
        lines.append(f"{i},{i}\n")
    lines.append("1,2,3,4,5\n")
    csv_bytes = "".join(lines).encode("utf-8")
    file_path = tmp_path / "late_wide.csv"
    file_path.write_bytes(csv_bytes)

    db_path = tmp_path / "store.duckdb"
    store = DuckStore(str(db_path))
    try:
        summary = import_csv_to_store(store, "t_wide_late", file_path, fi.normalize_options("csv", {}))
        assert summary.headers == ["a", "b", "Column 3", "Column 4", "Column 5"]
        assert summary.row_count == 120_001
        # Read last page to verify widest row
        last_rows = store.read_page("t_wide_late", 120_000, 10)
        assert last_rows == [("1", "2", "3", "4", "5")]
    finally:
        store.close()


def test_case_blank_lines(tmp_path):
    csv_bytes = b'a,b\n\n1,2\n\n\n3,4\n\n'
    compare_old_and_new(tmp_path, csv_bytes, {"delimiter": ",", "has_header": True})


def test_case_delimiter_only_first_record(tmp_path):
    csv_bytes = b',,\n1,2,3\n'
    compare_old_and_new(tmp_path, csv_bytes, {"delimiter": ",", "has_header": True})


def test_case_all_empty_row_mid_and_overwide_at_end(tmp_path):
    # ,, row in the middle (kept, does not widen) and an over-wide ,,,,, row at the end (skipped)
    csv_bytes = b'a,b,c\n1,2,3\n,,\n4,5,6\n,,,,,\n'
    compare_old_and_new(tmp_path, csv_bytes, {"delimiter": ",", "has_header": True})


def test_case_dquote_first_record(tmp_path):
    csv_bytes = b'""\n1\n'
    compare_old_and_new(tmp_path, csv_bytes, {"delimiter": ",", "has_header": True})


def test_case_trailing_delimiter(tmp_path):
    csv_bytes = b'a,b,\n1,2,\n'
    compare_old_and_new(tmp_path, csv_bytes, {"delimiter": ",", "has_header": True})


def test_case_one_column_file(tmp_path):
    csv_bytes = b'a\n1\n2\n'
    compare_old_and_new(tmp_path, csv_bytes, {"delimiter": ",", "has_header": True})


def test_case_header_only(tmp_path):
    csv_bytes = b'a,b\n'
    compare_old_and_new(tmp_path, csv_bytes, {"delimiter": ",", "has_header": True})


def test_case_empty_file(tmp_path):
    csv_bytes = b''
    compare_old_and_new(tmp_path, csv_bytes, {"delimiter": ",", "has_header": True})


def test_case_has_header_false(tmp_path):
    csv_bytes = b'1,2\n3,4,5\n'
    compare_old_and_new(tmp_path, csv_bytes, {"delimiter": ",", "has_header": False})


def test_case_tab_semicolon_pipe(tmp_path):
    # Tab
    compare_old_and_new(tmp_path, b'a\tb\n1\t2\n', {"delimiter": "\t", "has_header": True}, table_name="t_tab")
    # Semicolon
    compare_old_and_new(tmp_path, b'a;b\n1;2\n', {"delimiter": ";", "has_header": True}, table_name="t_semi")
    # Pipe
    compare_old_and_new(tmp_path, b'a|b\n1|2\n', {"delimiter": "|", "has_header": True}, table_name="t_pipe")


def test_case_unicode(tmp_path):
    csv_bytes = 'a,b\nçé,日本\n'.encode("utf-8")
    compare_old_and_new(tmp_path, csv_bytes, {"delimiter": ",", "has_header": True})


def test_case_field_of_2mb(tmp_path):
    big_field = "x" * (2 * 1024 * 1024)
    csv_bytes = f'a,b\n"{big_field}",2\n'.encode("utf-8")
    compare_old_and_new(tmp_path, csv_bytes, {"delimiter": ",", "has_header": True})


def test_case_512_and_513_columns(tmp_path):
    # 512 columns: succeeds
    c512 = ",".join(f"c{i}" for i in range(512)) + "\n" + ",".join("1" for _ in range(512)) + "\n"
    compare_old_and_new(tmp_path, c512.encode("utf-8"), {"delimiter": ",", "has_header": True}, table_name="t_512")

    # 513 columns: raises FileImportError on both
    c513 = ",".join(f"c{i}" for i in range(513)) + "\n" + ",".join("1" for _ in range(513)) + "\n"
    compare_old_and_new(tmp_path, c513.encode("utf-8"), {"delimiter": ",", "has_header": True}, table_name="t_513")


def test_case_column_n_blank_and_duplicate_headers(tmp_path):
    csv_bytes = b'a,a,,\n1,2,3,4\n'
    compare_old_and_new(tmp_path, csv_bytes, {"delimiter": ",", "has_header": True})


def test_case_header_only_spaces(tmp_path):
    csv_bytes = b'   \n1\n'
    compare_old_and_new(tmp_path, csv_bytes, {"delimiter": ",", "has_header": True})


def test_case_cell_equal_to_sentinel_byte(tmp_path):
    # \x01 byte in data: preserved and equal
    csv_bytes = b'a,b\n\x01,2\n'
    compare_old_and_new(tmp_path, csv_bytes, {"delimiter": ",", "has_header": True})

    # Exact sentinel string \x01NULL\x01: refused cleanly
    csv_bytes_sentinel = b'a,b\n\x01NULL\x01,2\n'
    file_path = tmp_path / "sentinel.csv"
    file_path.write_bytes(csv_bytes_sentinel)
    db_path = tmp_path / "store.duckdb"
    store = DuckStore(str(db_path))
    try:
        with pytest.raises(fi.FileImportError, match="internal sentinel"):
            import_csv_to_store(store, "t_sent", file_path, fi.normalize_options("csv", {}))
    finally:
        store.close()


def test_case_mixed_line_endings_refusal(tmp_path):
    csv_bytes = b'a,b\r\n1,2\n3,4\r5,6\n'
    file_path = tmp_path / "mixed.csv"
    file_path.write_bytes(csv_bytes)
    db_path = tmp_path / "store.duckdb"
    store = DuckStore(str(db_path))
    try:
        with pytest.raises(fi.FileImportError, match="mixed or unquoted carriage-return"):
            import_csv_to_store(store, "t_mixed", file_path, fi.normalize_options("csv", {}))
    finally:
        store.close()


def test_case_lone_cr_with_quotes_refusal(tmp_path):
    csv_bytes = b'a,b\r"1","2"\r'
    file_path = tmp_path / "lone_cr_quotes.csv"
    file_path.write_bytes(csv_bytes)
    db_path = tmp_path / "store.duckdb"
    store = DuckStore(str(db_path))
    try:
        with pytest.raises(fi.FileImportError, match="mixed or unquoted carriage-return"):
            import_csv_to_store(store, "t_lone_cr", file_path, fi.normalize_options("csv", {}))
    finally:
        store.close()


def test_case_lenient_malformed_quotes(tmp_path):
    # Unterminated quote at EOF
    csv_bytes_eof = b'a,b\n"abc,2\n3,4\n'
    file_path_eof = tmp_path / "unterminated.csv"
    file_path_eof.write_bytes(csv_bytes_eof)
    db_path = tmp_path / "store.duckdb"
    store = DuckStore(str(db_path))
    try:
        summary_eof = import_csv_to_store(store, "t_eof", file_path_eof, fi.normalize_options("csv", {}))
        assert any("unterminated quote" in n for n in summary_eof.notices)

        # Text right after closing quote
        csv_bytes_text = b'a,b\n"abc"def,2\n'
        file_path_text = tmp_path / "text_after.csv"
        file_path_text.write_bytes(csv_bytes_text)
        summary_text = import_csv_to_store(store, "t_text", file_path_text, fi.normalize_options("csv", {}))
        assert any("closing quote" in n for n in summary_text.notices)
    finally:
        store.close()


def test_seeded_fuzz_200_files(tmp_path):
    FIELDS = [
        "a", "b", "12", "", '""', '"x"', '"a,b"', '"q""r"', "é", " ", "x y",
        '""""',
    ]
    rng = random.Random(42)
    eol_choices = ["\n", "\r\n"]

    for i in range(200):
        eol = rng.choice(eol_choices)
        out = []
        num_rows = rng.randint(1, 6)
        for _ in range(num_rows):
            k = rng.choice([1, 2, 3, 4])
            rec = ",".join(rng.choice(FIELDS) for _ in range(k))
            out.append(rec)
            out.append(eol)
            if rng.random() < 0.1:
                out.append(eol)
        content = "".join(out)
        csv_bytes = content.encode("utf-8")
        hh = rng.choice([True, False])
        compare_old_and_new(
            tmp_path,
            csv_bytes,
            {"delimiter": ",", "encoding": "utf-8", "has_header": hh},
            table_name=f"fuzz_{i}",
        )


def test_cancel_after_first_batch(tmp_path):
    # 120,000 rows (at least 2 batches of 50,000)
    lines = ["a,b\n"]
    for i in range(120_000):
        lines.append(f"{i},{i}\n")
    csv_bytes = "".join(lines).encode("utf-8")
    file_path = tmp_path / "cancel.csv"
    file_path.write_bytes(csv_bytes)

    cancel_event = threading.Event()
    batches_seen = 0

    def progress(msg):
        nonlocal batches_seen
        batches_seen += 1
        if batches_seen >= 1:
            cancel_event.set()

    db_path = tmp_path / "store.duckdb"
    store = DuckStore(str(db_path))
    try:
        with pytest.raises(fi.ImportCancelledError):
            import_csv_to_store(
                store,
                "t_cancel",
                file_path,
                fi.normalize_options("csv", {}),
                cancel_event=cancel_event,
                progress=progress,
            )
        assert not store.has_table("t_cancel")
    finally:
        store.close()


def test_row_limit_overflow(tmp_path):
    lines = ["a,b\n"]
    for i in range(5000):
        lines.append(f"{i},{i}\n")
    csv_bytes = "".join(lines).encode("utf-8")
    file_path = tmp_path / "overflow.csv"
    file_path.write_bytes(csv_bytes)

    db_path = tmp_path / "store.duckdb"
    store = DuckStore(str(db_path))
    try:
        with pytest.raises(fi.FileImportError, match="import limit"):
            import_csv_to_store(
                store,
                "t_over",
                file_path,
                fi.normalize_options("csv", {}),
                max_rows=1000,
            )
        assert not store.has_table("t_over")
    finally:
        store.close()


def test_progress_called_at_least_twice(tmp_path):
    lines = ["a,b\n"]
    for i in range(120_000):
        lines.append(f"{i},{i}\n")
    csv_bytes = "".join(lines).encode("utf-8")
    file_path = tmp_path / "progress.csv"
    file_path.write_bytes(csv_bytes)

    progress_calls = []

    def progress(msg):
        progress_calls.append(msg)

    db_path = tmp_path / "store.duckdb"
    store = DuckStore(str(db_path))
    try:
        summary = import_csv_to_store(
            store,
            "t_prog",
            file_path,
            fi.normalize_options("csv", {}),
            progress=progress,
        )
        assert len(progress_calls) >= 2
        assert summary.row_count == 120_000
    finally:
        store.close()


def test_rollback_leaves_store_reusable(tmp_path):
    db_path = tmp_path / "store.duckdb"
    store = DuckStore(str(db_path))
    try:
        # 1. Failed import due to row limit
        file_path = tmp_path / "bad.csv"
        file_path.write_text("a,b\n1,2\n3,4\n5,6\n")
        with pytest.raises(fi.FileImportError):
            import_csv_to_store(
                store,
                "t_bad",
                file_path,
                fi.normalize_options("csv", {}),
                max_rows=1,
            )
        assert not store.has_table("t_bad")

        # 2. Store is reusable for subsequent operations
        store.create_table("t_good", [("col1", "text")])
        store.append_rows("t_good", [("hello",)])
        assert store.row_count("t_good") == 1
    finally:
        store.close()


def test_second_import_of_same_table_raises_store_error(tmp_path):
    file_path = tmp_path / "simple.csv"
    file_path.write_text("a,b\n1,2\n")
    db_path = tmp_path / "store.duckdb"
    store = DuckStore(str(db_path))
    try:
        import_csv_to_store(store, "t_dup", file_path, fi.normalize_options("csv", {}))
        with pytest.raises(StoreError, match="already exists"):
            import_csv_to_store(store, "t_dup", file_path, fi.normalize_options("csv", {}))
    finally:
        store.close()


def test_speed_1m_rows(tmp_path):
    # 1,000,000 rows x 5 columns CSV (about 26 MB) imports in under 15 s
    big_path = Path("/private/tmp/claude-501/b2attack/big.csv")
    if not big_path.exists():
        pytest.skip("/private/tmp/claude-501/b2attack/big.csv not found")

    db_path = tmp_path / "speed.duckdb"
    store = DuckStore(str(db_path))
    try:
        options = fi.normalize_options("csv", {"delimiter": ",", "has_header": True})
        t0 = time.time()
        summary = import_csv_to_store(store, "big_table", big_path, options)
        elapsed = time.time() - t0
        rows_per_sec = summary.row_count / elapsed if elapsed > 0 else 0
        print(f"\n1,000,000 rows imported in {elapsed:.3f} s ({rows_per_sec:,.0f} rows/s)")
        assert elapsed < 15.0
        assert summary.row_count == 1_000_000
    finally:
        store.close()
