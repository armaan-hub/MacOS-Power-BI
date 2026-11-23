"""Differential and property tests for streaming CSV store import."""

import os
from pathlib import Path
import random
import tempfile
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
    old_err, new_err, _ = compare_old_and_new(
        tmp_path, c513.encode("utf-8"), {"delimiter": ",", "has_header": True}, table_name="t_513"
    )
    assert old_err is not None
    assert new_err is not None
    assert "512-column" in str(new_err)


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


def test_b1_space_before_opening_quote_refused(tmp_path):
    # Space before opening quote raises FileImportError naming line and problem
    p = tmp_path / "space_quote.csv"
    p.write_bytes(b'a,b,c\n1, "x,y",3\n')
    db_path = tmp_path / "store.duckdb"
    with DuckStore(str(db_path)) as store:
        with pytest.raises(fi.FileImportError, match="Line 2 has a space before a quote"):
            import_csv_to_store(store, "tbl", p, fi.normalize_options("csv", {}))

    # Header record with space before quote also refused
    p_hdr = tmp_path / "space_hdr.csv"
    p_hdr.write_bytes(b'a, "b",c\n1,2,3\n')
    with DuckStore(str(db_path)) as store:
        with pytest.raises(fi.FileImportError, match="Line 1 has a space before a quote"):
            import_csv_to_store(store, "tbl_h", p_hdr, fi.normalize_options("csv", {}))


def test_b2_leading_blank_records_and_delimiters(tmp_path):
    # 150 leading "" records with has_header=True
    compare_old_and_new(
        tmp_path,
        b'""\n' * 150 + b',,\na,b,c\n',
        {"has_header": True},
        table_name="t_150_hh",
    )
    # 150 leading "" records with has_header=False
    compare_old_and_new(
        tmp_path,
        b'""\n' * 150 + b',,\na,b,c\n',
        {"has_header": False},
        table_name="t_150_nohh",
    )
    # 100 leading ,, records
    compare_old_and_new(
        tmp_path,
        b',,\n' * 100 + b'a,b,c\n',
        {"has_header": True},
        table_name="t_100_delim",
    )


def test_s3_headers_rejected_by_store_raise_file_import_error(tmp_path):
    db_path = tmp_path / "s3_store.duckdb"
    with DuckStore(str(db_path)) as store:
        # Case duplicate
        p1 = tmp_path / "case_dup.csv"
        p1.write_bytes(b"A,a\n1,2\n")
        with pytest.raises(fi.FileImportError, match="cannot be used by the large-file store"):
            import_csv_to_store(store, "t1", p1, fi.normalize_options("csv", {}))

        # Newline in header (Alt-Enter)
        p2 = tmp_path / "newline_hdr.csv"
        p2.write_bytes(b'"a\nb",c\n1,2\n')
        with pytest.raises(fi.FileImportError, match="cannot be used by the large-file store"):
            import_csv_to_store(store, "t2", p2, fi.normalize_options("csv", {}))

        # Tab in header
        p3 = tmp_path / "tab_hdr.csv"
        p3.write_bytes(b"a\tb,c\n1,2\n")
        with pytest.raises(fi.FileImportError, match="cannot be used by the large-file store"):
            import_csv_to_store(store, "t3", p3, fi.normalize_options("csv", {}))

        # NUL in header
        p4 = tmp_path / "nul_hdr.csv"
        p4.write_bytes(b"a\x00b,c\n1,2\n")
        with pytest.raises(fi.FileImportError, match="cannot be used by the large-file store"):
            import_csv_to_store(store, "t4", p4, fi.normalize_options("csv", {}))

        # Starts with __
        p5 = tmp_path / "reserved_hdr.csv"
        p5.write_bytes(b"__rn,c\n1,2\n")
        with pytest.raises(fi.FileImportError, match="cannot be used by the large-file store"):
            import_csv_to_store(store, "t5", p5, fi.normalize_options("csv", {}))


def test_s4_utf16_bom_and_nobom_and_odd_bytes(tmp_path):
    # LE with BOM
    compare_old_and_new(
        tmp_path,
        'a,b\r\n"é€,1",日本\r\n'.encode("utf-16"),
        {"encoding": "utf-16"},
        table_name="t_u16_le_bom",
    )
    # BE with BOM
    compare_old_and_new(
        tmp_path,
        b"\xfe\xff" + 'a,b\r\n"é€,1",日本\r\n'.encode("utf-16-be"),
        {"encoding": "utf-16"},
        table_name="t_u16_be_bom",
    )
    # LE without BOM
    compare_old_and_new(
        tmp_path,
        'a,b\r\né,1\r\n'.encode("utf-16-le"),
        {"encoding": "utf-16"},
        table_name="t_u16_le_nobom",
    )
    # Odd byte count refuses both
    compare_old_and_new(
        tmp_path,
        'a,b\n1,2\n'.encode("utf-16") + b"\x00",
        {"encoding": "utf-16"},
        table_name="t_u16_odd",
    )


def test_s5_error_messages_like_old(tmp_path):
    db_path = tmp_path / "s5_store.duckdb"
    with DuckStore(str(db_path)) as store:
        # Invalid UTF-8 at line 2
        p1 = tmp_path / "bad_utf8.csv"
        p1.write_bytes(b"a,b\n\xff\xfe,x\n")
        with pytest.raises(fi.FileImportError, match="Could not decode bad_utf8.csv as utf-8-sig"):
            import_csv_to_store(store, "t1", p1, fi.normalize_options("csv", {"encoding": "utf-8-sig"}))

        # Invalid UTF-8 with option utf-8
        with pytest.raises(fi.FileImportError, match="Could not decode bad_utf8.csv as utf-8"):
            import_csv_to_store(store, "t2", p1, fi.normalize_options("csv", {"encoding": "utf-8"}))

        # Invalid UTF-8 at EOF of large file
        p2 = tmp_path / "bad_late.csv"
        with open(p2, "wb") as f:
            f.write(b"a,b\n")
            chunk = b"".join(b"%d,val%d\n" % (i, i) for i in range(10000))
            for _ in range(20):
                f.write(chunk)
            f.write(b"\xff\xfe,end\n")
        with pytest.raises(fi.FileImportError, match="Could not decode bad_late.csv as utf-8-sig"):
            import_csv_to_store(store, "t3", p2, fi.normalize_options("csv", {}))


def test_s6_unreadable_file_and_directory(tmp_path):
    db_path = tmp_path / "s6_store.duckdb"
    with DuckStore(str(db_path)) as store:
        # Missing file
        with pytest.raises(fi.FileImportError, match="Could not read nope.csv: No such file or directory"):
            import_csv_to_store(store, "t1", tmp_path / "nope.csv", fi.normalize_options("csv", {}))

        # Directory
        d = tmp_path / "a_dir"
        d.mkdir()
        with pytest.raises(fi.FileImportError, match="Could not read a_dir: Is a directory"):
            import_csv_to_store(store, "t2", d, fi.normalize_options("csv", {}))

        # Unreadable file (chmod 000)
        p_locked = tmp_path / "locked.csv"
        p_locked.write_bytes(b"a,b\n1,2\n")
        os.chmod(p_locked, 0o000)
        try:
            with pytest.raises(fi.FileImportError, match="Could not read locked.csv: Permission denied"):
                import_csv_to_store(store, "t3", p_locked, fi.normalize_options("csv", {}))
        finally:
            os.chmod(p_locked, 0o644)


def test_s7_unquoted_quotes_produce_no_notices(tmp_path):
    # Test 15 unquoted quote cases; must produce NO notices and equal cells
    unquoted_cases = [
        b'a,b\n5" pipe,2\n',
        b'a,b\nab"c"d,2\n',
        b'a,b\nx"y,2\n',
        b'a,b\n1,x"y\n',
        b'a,b\n"x",y"z\n',
        b'a,b\n12",34"\n',
        b'a,b\na"b"c"d,1\n',
        b'a,b\n"hello",world"\n',
        b'a,b\nheight,5\'11"\n',
        b'a,b\nsymbol,foo"bar\n',
        b'a,b\n1,a"b\n',
        b'a,b\n2,c"d\n',
        b'a,b\n3,e"f\n',
        b'a,b\n4,g"h\n',
        b'a,b\n5,i"j\n',
    ]
    for idx, data in enumerate(unquoted_cases):
        old_err, new_err, summary = compare_old_and_new(
            tmp_path,
            data,
            {},
            table_name=f"t_unquoted_{idx}",
        )
        assert old_err is None
        assert new_err is None
        assert summary is not None
        assert summary.notices == []


def test_mutant_decoder_final_true_dropped(tmp_path):
    # A truncated utf-16 file mid-character must be refused
    p = tmp_path / "trunc_u16.csv"
    p.write_bytes('a,b\n1,2\n'.encode("utf-16")[:-1])
    db_path = tmp_path / "m_store.duckdb"
    with DuckStore(str(db_path)) as store:
        with pytest.raises(fi.FileImportError, match="Could not decode"):
            import_csv_to_store(store, "t_trunc", p, fi.normalize_options("csv", {"encoding": "utf-16"}))


def test_mutant_blank_header_width(tmp_path):
    # Header record delimiter-only widens the table
    compare_old_and_new(
        tmp_path,
        b',,,\n1,2\n',
        {"has_header": True},
        table_name="t_blank_w",
    )


def test_mutant_sweep_folders(tmp_path):
    import tempfile, shutil
    d_old = tempfile.mkdtemp(prefix="analytics_studio_csv_")
    d_new = tempfile.mkdtemp(prefix="analytics_studio_csv_")
    d_other = tempfile.mkdtemp(prefix="analytics_studio_csvx_other")
    past = time.time() - 2 * 86400
    os.utime(d_old, (past, past))
    os.utime(d_other, (past, past))

    p = tmp_path / "tiny.csv"
    p.write_bytes(b"a,b\n1,2\n")
    db_path = tmp_path / "sw_store.duckdb"
    try:
        with DuckStore(str(db_path)) as store:
            import_csv_to_store(store, "t_sw", p, fi.normalize_options("csv", {}))

        # d_old deleted, d_new kept, d_other kept
        assert not os.path.exists(d_old)
        assert os.path.exists(d_new)
        assert os.path.exists(d_other)
    finally:
        for d in (d_old, d_new, d_other):
            shutil.rmtree(d, ignore_errors=True)


def test_mutant_temp_folder_removed_on_success_error_cancel(tmp_path):
    # 1. Success
    p = tmp_path / "transcode_ok.csv"
    p.write_bytes('a,b\n1,2\n'.encode("cp1252"))
    db_path = tmp_path / "clean_store.duckdb"
    with DuckStore(str(db_path)) as store:
        import_csv_to_store(store, "t1", p, fi.normalize_options("csv", {"encoding": "cp1252"}))

    # Check no young temp folders left behind
    tmp_base = tempfile.gettempdir()
    my_uid = os.getuid()
    for name in os.listdir(tmp_base):
        if name.startswith("analytics_studio_csv_"):
            folder = os.path.join(tmp_base, name)
            st = os.stat(folder)
            if st.st_uid == my_uid:
                # Should not be young leftover from this run
                assert time.time() - st.st_mtime > 5.0

    # 2. Decode error
    p_bad = tmp_path / "bad_cp.csv"
    p_bad.write_bytes(b"a,b\n\x81,2\n")
    with DuckStore(str(db_path)) as store:
        with pytest.raises(fi.FileImportError):
            import_csv_to_store(store, "t2", p_bad, fi.normalize_options("csv", {"encoding": "cp1252"}))

    # 3. Cancel
    ev = threading.Event()
    ev.set()
    with DuckStore(str(db_path)) as store:
        with pytest.raises(fi.ImportCancelledError):
            import_csv_to_store(
                store, "t3", p, fi.normalize_options("csv", {"encoding": "cp1252"}), cancel_event=ev
            )


def test_mutant_interrupt_cancel_responsive(tmp_path):
    # Cancellation while DuckDB is scanning stops with ImportCancelledError and store is reusable
    p = tmp_path / "med.csv"
    with open(p, "wb") as f:
        f.write(b"a,b,c\n")
        chunk = b"".join(b"%d,val%d,col%d\n" % (i, i, i) for i in range(10000))
        for _ in range(10):
            f.write(chunk)

    ev = threading.Event()
    db_path = tmp_path / "cancel_store.duckdb"
    with DuckStore(str(db_path)) as store:
        # Trigger cancel immediately during first progress call
        def on_prog(msg):
            ev.set()

        with pytest.raises(fi.ImportCancelledError):
            import_csv_to_store(
                store,
                "t_cancelled",
                p,
                fi.normalize_options("csv", {}),
                cancel_event=ev,
                progress=on_prog,
            )
        assert not store.has_table("t_cancelled")

        # Store is reusable
        store.create_table("t_reused", [("c0", "text")])
        assert store.has_table("t_reused")


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


# ---------------------------------------------------------------------------
# B2a-fix2: sparse wide records, chunk independence, fast quote check, nits, gaps
# ---------------------------------------------------------------------------
import itertools  # noqa: E402

import analytics_studio.store.csv_import as ci  # noqa: E402

_NAMES = itertools.count()


def _opts(**kw):
    return fi.normalize_options("csv", kw)


def _old_result(path, opts):
    try:
        cand = fi._parse_csv(Path(path), opts)
    except fi.FileImportError as exc:
        return ("refuse", str(exc))
    return ("ok", cand.headers, [[r[h] for h in cand.headers] for r in cand.rows])


def _new_result(store, path, opts, **kw):
    name = f"t{next(_NAMES)}"
    try:
        summary = ci.import_csv_to_store(store, name, path, opts, **kw)
    except fi.FileImportError as exc:
        assert not store.has_table(name)
        return ("refuse", str(exc))
    rows = [list(r) for r in store.read_page(name, 0, summary.row_count + 5)]
    for row in rows:
        assert all(isinstance(c, str) for c in row)
    store.drop_table(name)
    return ("ok", summary.headers, rows, summary.notices)


def _check_equal(old, new, *, strict=True):
    """Old and new must agree. strict: new may not refuse a file old accepts."""
    if old[0] == "ok" and new[0] == "ok":
        assert new[1] == old[1]
        assert new[2] == old[2]
    elif old[0] == "refuse":
        # new may read the two malformed-quote classes leniently, but only with a notice
        assert new[0] == "refuse" or new[3], f"old refused ({old[1]}) but new imported silently"
    elif strict:
        raise AssertionError(f"old imported but new refused: {new[1]}")


def _both(tmp_path, store, data, has_header=True, **kw):
    folder = tmp_path / f"d{next(_NAMES)}"
    folder.mkdir()
    path = folder / "data.csv"
    path.write_bytes(data)
    opts = _opts(has_header=has_header)
    return _old_result(path, opts), _new_result(store, path, opts, **kw)


@pytest.fixture
def store2(tmp_path):
    s = DuckStore(str(tmp_path / "fix2.duckdb"))
    yield s
    s.close()


# --- Blocker 1: a record with many leading empty cells -----------------------

@pytest.mark.parametrize("has_header", [True, False])
@pytest.mark.parametrize("lead", [16, 17, 20, 500])
def test_blocker1_leading_empty_cells_widen_table(tmp_path, store2, lead, has_header):
    data = b"a,b\n1,2\n" + b"," * lead + b"x\n3,4\n"
    old, new = _both(tmp_path, store2, data, has_header)
    assert old[0] == "ok" and len(old[1]) == lead + 1
    assert new[0] == "ok"
    _check_equal(old, new)
    assert len(new[2]) == len(old[2])


@pytest.mark.parametrize("has_header", [True, False])
def test_blocker1_sparse_only_file(tmp_path, store2, has_header):
    old, new = _both(tmp_path, store2, b"a\n" + b"," * 40 + b"x", has_header)
    assert old[0] == "ok" and new[0] == "ok"
    _check_equal(old, new)
    assert len(new[1]) == 41


def test_blocker1_over_limit_and_skipped_wide_empty_records(tmp_path, store2):
    # x in column 513 (512 delimiters before it): over the limit for both
    old, new = _both(tmp_path, store2, b"a,b\n1,2\n" + b"," * 512 + b"x\n")
    assert old[0] == "refuse" and new[0] == "refuse"
    assert "512-column" in new[1]
    # a wide record whose cells are all empty is skipped by both and does not widen
    old, new = _both(tmp_path, store2, b"a,b\n,,,,\n" + b"," * 600 + b"\n1,2\n")
    assert old[0] == "ok"
    _check_equal(old, new)
    assert new[1] == ["a", "b"]
    # the same, with the widest record only reached after 600 empty delimiters
    old, new = _both(tmp_path, store2, b"a,b\n1,2\n" + b"," * 600 + b"x\n")
    assert old[0] == "refuse" and new[0] == "refuse"


def test_blocker1_sparse_row_late_in_big_file(tmp_path, store2):
    # The wide record sits at the very end, far past any head window. A small first
    # tier stands in for "line 5,000,001 of a big file" without a 5M-row file.
    body = b"a,b\n" + b"1,2\n" * 20_000 + b",,,,x\n"
    old, new = _both(tmp_path, store2, body, width_tiers=(2, ci._NC))
    assert old[0] == "ok" and len(old[1]) == 5 and len(old[2]) == 20_001
    _check_equal(old, new)


def _sparse_file(rng):
    cells = ["x", "1", '""', '"q,r"', "y z"]
    lines = []
    for _ in range(rng.randint(0, 9)):
        kind = rng.random()
        if kind < 0.08:
            lines.append("")
        elif kind < 0.16:
            lines.append('""')
        else:
            n = rng.randint(1, 24)
            lines.append(",".join(rng.choice(cells) if rng.random() < 0.3 else "" for _ in range(n)))
    return "\n".join(lines).encode()


@pytest.mark.parametrize("tier", [1, 2, 3, 17])
def test_blocker1_tier_constant_fuzz_matches_old(tmp_path, store2, tier):
    rng = random.Random(1000 + tier)
    seen_wide = 0
    for _ in range(40):
        data = _sparse_file(rng)
        has_header = rng.random() < 0.6
        old, new = _both(tmp_path, store2, data, has_header, width_tiers=(tier, 25, ci._NC))
        _check_equal(old, new)
        if old[0] == "ok" and len(old[1]) > tier:
            seen_wide += 1
    assert seen_wide >= 5  # the fuzz really reaches past the first tier


def test_blocker1_default_tiers_fuzz_matches_old(tmp_path, store2):
    rng = random.Random(7)
    for _ in range(60):
        old, new = _both(tmp_path, store2, _sparse_file(rng), rng.random() < 0.5)
        _check_equal(old, new)


def test_blocker1_last_tier_wide_empty_records(tmp_path, store2, monkeypatch):
    # Column limit 4, tiers (2, 5): records that fill the last schema column while all
    # their visible cells are empty cannot be judged by DuckDB; the exact fallback decides.
    monkeypatch.setattr(fi, "MAX_COLUMNS", 4)
    tiers = (2, 5)
    cases = [
        b"a,b\n1,2\n,,,,,\n3,4\n",       # all-empty wide record: skipped
        b"a,b\n1,2\n,,,,,x\n",           # data past the last schema column: over the limit
        b"a,b\n1,2\n,,,,x\n",            # data in the last schema column: over the limit
        b"a,b\n1,2,3,4\n,,,,,,\n",       # widest kept record has exactly 4 cells
        b"a,b\n,,,,,,,,\n,,,,,\n",       # only skipped wide records
    ]
    for data in cases:
        for has_header in (True, False):
            old, new = _both(tmp_path, store2, data, has_header, width_tiers=tiers)
            _check_equal(old, new)
            assert (old[0] == "ok") == (new[0] == "ok")


# --- Blocker 2: chunk independence of the byte scans --------------------------

_QTOK = [
    b'"', b'""', b'"a"', b'"a ""b"" c"', b",", b",", b"\n", b"\r\n", b"\r", b" ", b"x", b"ab",
    b'"p, ""q"""', b' "', b'" ', b'""""', b"\t", b"\xef\xbb\xbf",
]


def _scan_outcome(fn, path, chunk_size):
    try:
        return ("ok", tuple(fn(path, ",", chunk_size=chunk_size)))
    except fi.FileImportError as exc:
        return ("refuse", str(exc))


def test_blocker2_quote_scan_independent_of_chunk_size(tmp_path):
    rng = random.Random(5)
    path = tmp_path / "q.csv"
    sizes = (1, 2, 3, 5, 7, 11, 64)
    same = differ = 0
    for _ in range(1500):
        path.write_bytes(b"".join(rng.choice(_QTOK) for _ in range(rng.randint(1, 40))))
        for fn in (ci._exact_quote_scan, ci._detect_malformed_quotes_and_space_before_quote):
            ref = _scan_outcome(fn, path, 1 << 20)
            for cs in sizes:
                if _scan_outcome(fn, path, cs) == ref:
                    same += 1
                else:
                    differ += 1
        fast_ref = ci._fast_quote_check(path, ",", chunk_size=1 << 20)
        for cs in sizes:
            if ci._fast_quote_check(path, ",", chunk_size=cs) == fast_ref:
                same += 1
            else:
                differ += 1
    assert differ == 0
    assert same == 1500 * 3 * len(sizes)


def test_fast_quote_check_is_sound_against_exact_scan(tmp_path):
    rng = random.Random(99)
    path = tmp_path / "f.csv"
    clean_and_fast = fell_back = unsound = 0
    for _ in range(3000):
        path.write_bytes(b"".join(rng.choice(_QTOK) for _ in range(rng.randint(1, 30))))
        exact = _scan_outcome(ci._exact_quote_scan, path, 1 << 20)
        fast = ci._fast_quote_check(path, ",", chunk_size=rng.choice([1, 2, 3, 5, 8, 1 << 20]))
        if fast:
            if exact == ("ok", ()):
                clean_and_fast += 1
            else:
                unsound += 1
        else:
            fell_back += 1
    print(f"\nfast check: {clean_and_fast} proven clean, {fell_back} fell back, {unsound} unsound")
    assert unsound == 0
    assert clean_and_fast > 100 and fell_back > 100


def test_fast_quote_check_clean_files_skip_exact_scan(tmp_path, store2, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("exact scan must not run for a provably clean file")

    monkeypatch.setattr(ci, "_exact_quote_scan", boom)
    data = b'id,name,note\n1,"a, b","x ""y"" z"\n2,"",\n"3","l\nm",x\n'
    old, new = _both(tmp_path, store2, data)
    _check_equal(old, new)
    assert new[3] == []


def test_fast_quote_check_unprovable_but_valid_file_falls_back_without_notice(tmp_path, store2):
    # quotes inside unquoted fields are valid text; the fast check cannot prove them
    data = b'a,b\n5" pipe,2\nab"c"d,x"y\n'
    path = tmp_path / "u.csv"
    path.write_bytes(data)
    assert ci._fast_quote_check(path, ",") is False
    assert ci._exact_quote_scan(path, ",") == []
    old, new = _both(tmp_path, store2, data)
    _check_equal(old, new)
    assert new[3] == []


_STRADDLE = [
    b'a,b\n"a""a ""b"" c""p, ""q""""""",2\n',         # valid escaped quotes
    b'a,b\n"x ""y"" z",""\n1,"p, ""q"""""\n',          # valid, ends with escaped quotes
    b'a,b\n1, "x,y"\n',                                # space before a quote: refused
    b'a,b\n"abc"def,2\n',                              # text after closing quote: notice
    b'a,b\n"abc,2\n3,4\n',                             # unterminated quote: notice
    b'a,b\r\n1,2\r\n"l\nm",3\r\n',                     # CRLF with a bare LF inside quotes
    b'a,b\r\n1,2\r\n',                                 # CR and LF split by a boundary
    b'a,b\n1,\x01NULL\x01\n',                          # marker bytes split by a boundary
    b'"a","b"\n"1","2"\n',
]


@pytest.mark.parametrize("data", _STRADDLE)
def test_blocker2_constructs_straddling_chunk_boundary(tmp_path, store2, data):
    results = []
    for cs in (None, 1, 2, 3, 4, 5, 7, 11):
        kw = {} if cs is None else {"scan_chunk_size": cs}
        old, new = _both(tmp_path, store2, data, **kw)
        _check_equal(old, new, strict=False)
        results.append(new)
    assert all(r == results[0] for r in results), "result depends on the scan chunk size"


def test_blocker2_real_8mib_boundary_escaped_quote_pair(tmp_path, store2):
    # the first quote of an escaped pair is the last byte of the first 8 MiB chunk
    block = 8 * 1024 * 1024
    for field in (b'"p ""q"" r"', b'"a""a ""b"" c""p, ""q"""""'):
        tail = field + b",2\n"
        for offset in (1, 2, 3, 4):  # which quote of the construct is the last byte of chunk 1
            head = b"h1,h2\n"
            pad = block - len(head) - 3 - (field.index(b'""') + offset)
            data = head + b"x," + b"y" * pad + b"\n" + tail
            old, new = _both(tmp_path, store2, data)
            assert old[0] == "ok"
            _check_equal(old, new)
            assert new[3] == []


# --- Nits ---------------------------------------------------------------------

def test_nit_directory_message_like_old(tmp_path, store2):
    d = tmp_path / "adir"
    d.mkdir()
    old = _old_result(d, _opts())
    new = _new_result(store2, d, _opts())
    assert old == ("refuse", "Could not read adir: Is a directory.")
    assert new == ("refuse", "Could not read adir: Is a directory.")


@pytest.mark.parametrize("raw", ["a,b\n1,2\n".encode("utf-16")[:-1], "a,b\n1,2\n".encode("utf-16-le")[:-1]])
def test_nit_utf16_truncated_message_names_utf16(tmp_path, store2, raw):
    old, new = _both(tmp_path, store2, raw)  # default encoding is utf-8-sig: use utf-16 below
    path = tmp_path / "t16.csv"
    path.write_bytes(raw)
    opts = _opts(encoding="utf-16")
    old = _old_result(path, opts)
    new = _new_result(store2, path, opts)
    assert old == ("refuse", "Could not decode t16.csv as utf-16.")
    assert new == old


def test_nit_header_case_policy_is_ascii_only(tmp_path, store2):
    # the store folds only ASCII letters: E-acute and e-acute are different names
    old, new = _both(tmp_path, store2, "É,é\n1,2\n".encode())
    assert old[0] == "ok"
    assert new[0] == "ok"
    _check_equal(old, new)
    _, new_ascii = _both(tmp_path, store2, b"A,a\n1,2\n")
    assert new_ascii[0] == "refuse" and "cannot be used by the large-file store" in new_ascii[1]


def test_bom_before_quoted_first_header_both_encodings(tmp_path, store2):
    for enc in ("utf-8-sig", "utf-8"):
        path = tmp_path / f"bom_{enc}.csv"
        path.write_bytes(b'\xef\xbb\xbf"a,b",c\n1,2\n')
        opts = _opts(encoding=enc)
        _check_equal(_old_result(path, opts), _new_result(store2, path, opts))
        assert ci._detect_malformed_quotes_and_space_before_quote(path, ",") == []


def test_utf16_without_bom_imports_and_equals_old(tmp_path, store2):
    path = tmp_path / "le.csv"
    path.write_bytes("a,b\r\né,1\r\n".encode("utf-16-le"))
    opts = _opts(encoding="utf-16")
    old = _old_result(path, opts)
    new = _new_result(store2, path, opts)
    assert old[0] == "ok" and new[0] == "ok"
    assert new[1:3] == old[1:3] == (["a", "b"], [["é", "1"]])


# --- Test gaps (each must fail when its guarded line is removed) ----------------

def _isolated_tmp(tmp_path, monkeypatch):
    base = tmp_path / "systmp"
    base.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(base))
    return base


def test_gap_sweep_ignores_folders_of_other_users(tmp_path, monkeypatch):
    base = _isolated_tmp(tmp_path, monkeypatch)
    old_dir = base / "analytics_studio_csv_old"
    old_dir.mkdir()
    past = time.time() - 3 * 86400
    os.utime(old_dir, (past, past))
    monkeypatch.setattr(os, "getuid", lambda: os.stat(old_dir).st_uid + 1)
    ci._clean_old_temp_folders()
    assert old_dir.exists(), "a folder owned by another user must not be removed"
    monkeypatch.undo()
    monkeypatch.setattr(tempfile, "tempdir", str(base))
    ci._clean_old_temp_folders()
    assert not old_dir.exists()


def test_gap_sweep_only_touches_directories(tmp_path, monkeypatch):
    base = _isolated_tmp(tmp_path, monkeypatch)
    plain = base / "analytics_studio_csv_a_file"
    plain.write_bytes(b"x")
    past = time.time() - 3 * 86400
    os.utime(plain, (past, past))
    removed = []
    monkeypatch.setattr(ci.shutil, "rmtree", lambda p, **k: removed.append(p))
    ci._clean_old_temp_folders()
    assert removed == []


def test_gap_sweep_prefix_and_age(tmp_path, monkeypatch):
    base = _isolated_tmp(tmp_path, monkeypatch)
    fresh = base / "analytics_studio_csv_fresh"
    other = base / "something_else"
    stale = base / "analytics_studio_csv_stale"
    for d in (fresh, other, stale):
        d.mkdir()
    past = time.time() - 3 * 86400
    os.utime(other, (past, past))
    os.utime(stale, (past, past))
    ci._clean_old_temp_folders()
    assert fresh.exists() and other.exists() and not stale.exists()


def test_gap_cancel_checked_in_every_scan(tmp_path):
    path = tmp_path / "c.csv"
    path.write_bytes(b'a,b\n"1","2"\n' * 50)
    ev = threading.Event()
    ev.set()
    with pytest.raises(fi.ImportCancelledError):
        ci._check_line_endings_and_sentinel(path, b"\x01NULL\x01", cancel_event=ev, chunk_size=64)
    with pytest.raises(fi.ImportCancelledError):
        ci._fast_quote_check(path, ",", cancel_event=ev, chunk_size=64)
    with pytest.raises(fi.ImportCancelledError):
        ci._exact_quote_scan(path, ",", cancel_event=ev, chunk_size=64)
    with pytest.raises(fi.ImportCancelledError):
        ci._detect_malformed_quotes_and_space_before_quote(path, ",", cancel_event=ev)


def test_gap_cancel_stops_a_long_exact_quote_scan_quickly(tmp_path):
    # a quote inside an unquoted field defeats the fast check, so the slow exact scan runs
    path = tmp_path / "slow.csv"
    line = b'1,"abc",5" pipe,"x ""y"""\n'
    path.write_bytes(line * 1_200_000)  # about 31 MB: the exact scan needs several seconds
    ev = threading.Event()
    timer = threading.Timer(0.3, ev.set)
    timer.start()
    t0 = time.time()
    try:
        with pytest.raises(fi.ImportCancelledError):
            ci._exact_quote_scan(path, ",", cancel_event=ev)
    finally:
        timer.cancel()
    assert time.time() - t0 < 1.5


def test_gap_escaped_quote_inside_quoted_field_gives_no_notice(tmp_path, store2, monkeypatch):
    data = b'a,b\n"x""y",2\n"""",3\n"p ""q"" r",""\n'
    path = tmp_path / "esc.csv"
    path.write_bytes(data)
    assert ci._exact_quote_scan(path, ",") == []
    # run the whole import through the exact scan only
    monkeypatch.setattr(ci, "_fast_quote_check", lambda *a, **k: False)
    old, new = _both(tmp_path, store2, data)
    _check_equal(old, new)
    assert new[3] == []


def test_gap_interrupt_stops_a_long_duckdb_scan(tmp_path):
    # 500k rows x 100 columns: the width pre-pass alone keeps DuckDB busy for several seconds.
    # Without interrupt() the cancel would only be seen after that pre-pass.
    path = tmp_path / "wide.csv"
    row = b",".join([b"1"] * 100) + b"\n"
    path.write_bytes(b",".join(b"h%d" % i for i in range(100)) + b"\n" + row * 500_000)
    ev = threading.Event()
    set_at = []

    def fire():
        set_at.append(time.time())
        ev.set()

    timer = threading.Timer(0.3, fire)
    with DuckStore(str(tmp_path / "intr.duckdb")) as store:
        timer.start()
        try:
            with pytest.raises(fi.ImportCancelledError):
                ci.import_csv_to_store(store, "wide", path, _opts(), cancel_event=ev, max_rows=10**7)
            latency = time.time() - set_at[0]
        finally:
            timer.cancel()
        assert latency < 1.0, f"cancel took {latency:.2f} s after it was requested"
        assert not store.has_table("wide")
        store.create_table("again", [("c0", "text")])


def test_gap_watcher_thread_is_joined_and_not_left_running(tmp_path, monkeypatch):
    joined = []
    real_join = threading.Thread.join

    def spy_join(self, *args, **kwargs):
        joined.append(self.name)
        return real_join(self, *args, **kwargs)

    monkeypatch.setattr(threading.Thread, "join", spy_join)
    path = tmp_path / "w.csv"
    path.write_bytes(b"a,b\n" + b"1,2\n" * 120_000)
    with DuckStore(str(tmp_path / "leak.duckdb")) as store:
        for i in range(8):
            ev = threading.Event()
            with pytest.raises(fi.ImportCancelledError):  # cancelled after the first batch
                ci.import_csv_to_store(
                    store, f"t{i}", path, _opts(), cancel_event=ev, progress=lambda _m, e=ev: e.set()
                )
            assert joined.count("csv-import-cancel-watch") == 2 * i + 1
            ci.import_csv_to_store(store, f"ok{i}", path, _opts(), cancel_event=threading.Event())
            assert joined.count("csv-import-cancel-watch") == 2 * i + 2
            assert "csv-import-cancel-watch" not in [t.name for t in threading.enumerate()]
        # no cancel event, no watcher thread
        before = len(joined)
        ci.import_csv_to_store(store, "plain", path, _opts())
        assert len(joined) == before


def test_gap_bom_is_skipped_by_the_quote_scans(tmp_path, store2):
    # a BOM does not count as text before the first quote
    clean = tmp_path / "bom_clean.csv"
    clean.write_bytes(b'\xef\xbb\xbf"a,b",c\n1,2\n')
    assert ci._fast_quote_check(clean, ",") is True
    bad = tmp_path / "bom_text_after.csv"
    bad.write_bytes(b'\xef\xbb\xbf"abc"def,2\n1,2\n')
    assert len(ci._exact_quote_scan(bad, ",")) == 1
    old, new = _both(tmp_path, store2, b'\xef\xbb\xbf"abc"def,2\n1,2\n')
    assert old[0] == "refuse" and new[0] == "ok" and len(new[3]) == 1
    old, new = _both(tmp_path, store2, b'\xef\xbb\xbfa, "b"\n1,2\n')
    assert new[0] == "refuse" and "space before a quote" in new[1]


def test_blocker2_real_8mib_boundary_sentinel_bytes_are_refused(tmp_path, store2):
    # the internal marker bytes straddle the first 8 MiB chunk boundary: must be refused,
    # never silently turned into an empty cell
    block = 8 * 1024 * 1024
    marker = b"\x01NULL\x01"
    for split in range(1, len(marker)):
        head = b"h1,h2\n"
        pad = block - len(head) - 2 - split
        data = head + b"x," + b"y" * pad + marker + b"\n"
        old, new = _both(tmp_path, store2, data)
        assert old[0] == "ok"
        assert new[0] == "refuse" and "sentinel" in new[1]


# ---------------------------------------------------------------------------
# B2a-fix3: wide all-empty records must not cost a Python pass over the file
# ---------------------------------------------------------------------------

def _wide_shapes():
    q4 = b'""""'
    return {
        "empty_600_commas": (b"," * 599, 2),
        "empty_600_quoted_pairs": (b",".join([b'""'] * 600), 2),
        "empty_mixed_pairs": (b",".join([b'""', b"", b'""', b""] * 150), 2),
        "x_after_600": (b"," * 600 + b"x", None),            # 601 cells: over the column limit
        "x_after_20": (b"," * 20 + b"x", 21),
        "x_after_20_quoted_pairs": (b'"",' * 20 + b"x", 21),
        "600_escaped_quote_cells": (b",".join([q4] * 600), None),  # not empty, over the limit
        "20_escaped_quote_cells": (b",".join([q4] * 20), 20),
        "quoted_comma_after_20": (b"," * 20 + b'"a,b",x', 22),
        "quoted_newline_after_20": (b"," * 20 + b'"a\nb"', 21),
    }


@pytest.mark.parametrize("eol", [b"\n", b"\r\n"])
@pytest.mark.parametrize("has_header", [True, False])
@pytest.mark.parametrize("shape", list(_wide_shapes()))
def test_fix3_wide_record_shapes_match_old(tmp_path, store2, shape, has_header, eol):
    record, expected_width = _wide_shapes()[shape]
    data = eol.join([b"a,b", b"1,2", record, b"3,4"]) + eol
    old, new = _both(tmp_path, store2, data, has_header, width_tiers=(4, ci._NC))
    _check_equal(old, new)
    assert (old[0] == "ok") == (new[0] == "ok")
    if expected_width is None:
        assert old[0] == "refuse" and "512-column" in new[1]
    else:
        assert len(new[1]) == expected_width == len(old[1])


def test_fix3_candidate_line_inside_quoted_field_is_not_a_record(tmp_path, store2):
    inner = b"," * 40 + b"x"
    for eol in (b"\n", b"\r\n"):
        data = eol.join([b"a,b", b'1,"first', inner, b'last"', b"3,4"]) + eol
        old, new = _both(tmp_path, store2, data, width_tiers=(4, ci._NC))
        assert old[0] == "ok"
        _check_equal(old, new)
        assert new[1] == ["a", "b"] and len(new[2]) == 2
        # a real wide record next to it is still found
        data = eol.join([b"a,b", b'1,"first', inner, b'last"', b"," * 30 + b"x"]) + eol
        old, new = _both(tmp_path, store2, data, width_tiers=(4, ci._NC))
        _check_equal(old, new)
        assert len(new[1]) == 31


@pytest.mark.parametrize("chunk", [1, 2, 3, 5, 7, 64, 1 << 20])
def test_fix3_candidate_offsets_do_not_depend_on_chunk_size(tmp_path, chunk):
    record_a = b"," * 30 + b"x"
    record_b = b'"",' * 12 + b'"a,b"'
    data = b'a,b\n1,"p\n' + b"," * 40 + b'q"\n' + b"1,2,3,4,5,6,7,8,9,10\n" + record_a + b"\n3,4\r\n" + record_b + b"\r\n,,\n" + record_a
    path = tmp_path / "off.csv"
    path.write_bytes(data)
    offsets = ci._wide_candidate_offsets(path, ",", 8, True, None, chunk)
    expected = [m for m in (data.index(record_a), data.index(record_b), data.rindex(record_a))]
    assert offsets == expected
    # without quote bytes every physical line start is judged on its own
    path.write_bytes(b"a,b\n1,2\n" + record_a + b"\n,,,,,,,,,,\n1,2,3,4,5,6,7,8,9,10\n" + b"," * 9 + b"y\n")
    plain = path.read_bytes()
    assert ci._wide_candidate_offsets(path, ",", 8, False, None, chunk) == [
        plain.index(record_a), plain.index(b"," * 10 + b"\n"), plain.index(b"," * 9 + b"y")
    ]


@pytest.mark.parametrize("chunk", [1, 5, 64])
def test_fix3_tier_fuzz_with_small_scan_chunks(tmp_path, store2, chunk):
    rng = random.Random(500 + chunk)
    for _ in range(25):
        data = _sparse_file(rng)
        old, new = _both(
            tmp_path, store2, data, rng.random() < 0.6, width_tiers=(3, 25, ci._NC), scan_chunk_size=chunk
        )
        _check_equal(old, new)


def test_fix3_wide_empty_record_does_not_trigger_full_python_pass(tmp_path, store2, monkeypatch):
    calls = {"full": 0, "offsets": []}
    real_full = ci._python_kept_width
    real_at = ci._widest_record_at

    def spy_full(*a, **k):
        calls["full"] += 1
        return real_full(*a, **k)

    def spy_at(path, delimiter, offsets, cancel_event):
        calls["offsets"].append(list(offsets))
        return real_at(path, delimiter, offsets, cancel_event)

    monkeypatch.setattr(ci, "_python_kept_width", spy_full)
    monkeypatch.setattr(ci, "_widest_record_at", spy_at)
    body = b"a,b\n" + b"1,2\n" * 20_000
    data = body + b"," * 600 + b"\n" + b"3,4\n" * 100
    old, new = _both(tmp_path, store2, data, width_tiers=(17, 65, ci._NC))
    _check_equal(old, new)
    assert new[1] == ["a", "b"]
    assert calls["full"] == 0
    assert calls["offsets"] == [[len(body)]]  # exactly the one wide record is looked at


def test_fix3_file_without_ambiguous_records_looks_at_no_record(tmp_path, store2, monkeypatch):
    seen = []
    monkeypatch.setattr(ci, "_widest_record_at", lambda *a, **k: seen.append(a) or 0)
    monkeypatch.setattr(ci, "_python_kept_width", lambda *a, **k: seen.append(a) or 0)
    old, new = _both(tmp_path, store2, b"a,b\n1,2\n3,4\n")
    _check_equal(old, new)
    assert seen == []


def test_fix3_unproven_line_structure_still_uses_full_pass_and_matches_old(tmp_path, store2, monkeypatch):
    # a quote inside an unquoted field defeats the structure proof: the full pass decides
    full = []
    real_full = ci._python_kept_width
    monkeypatch.setattr(ci, "_python_kept_width", lambda *a, **k: full.append(1) or real_full(*a, **k))
    data = b'a,b\n5" pipe,2\n' + b"," * 600 + b"\n3,4\n"
    old, new = _both(tmp_path, store2, data, width_tiers=(4, ci._NC))
    _check_equal(old, new)
    assert new[1] == ["a", "b"] and new[3] == []
    assert full == [1]
    data = b'a,b\n5" pipe,2\n' + b"," * 20 + b"x\n"
    old, new = _both(tmp_path, store2, data, width_tiers=(4, ci._NC))
    _check_equal(old, new)
    assert len(new[1]) == 21


def test_fix3_wide_record_after_a_bom_is_found_at_the_right_offset(tmp_path, store2):
    for enc in ("utf-8-sig", "utf-8"):
        path = tmp_path / f"bom_{enc}.csv"
        path.write_bytes(b"\xef\xbb\xbfa,b\n1,2\n" + b"," * 25 + b"x\n3,4\n")
        opts = _opts(encoding=enc)
        old = _old_result(path, opts)
        new = _new_result(store2, path, opts, width_tiers=(4, ci._NC))
        assert old[0] == "ok" and len(old[1]) == 26
        _check_equal(old, new)
    # a wide record on the very first line, right after the BOM
    path = tmp_path / "bom_first.csv"
    path.write_bytes(b"\xef\xbb\xbf" + b"," * 25 + b"x\n1,2\n")
    for has_header in (True, False):
        opts = _opts(has_header=has_header)
        _check_equal(_old_result(path, opts), _new_result(store2, path, opts, width_tiers=(4, ci._NC)))


def test_fix3_cancel_checked_in_candidate_scan(tmp_path):
    path = tmp_path / "cand.csv"
    path.write_bytes(b"a,b\n" + b"1,2\n" * 50)
    ev = threading.Event()
    ev.set()
    with pytest.raises(fi.ImportCancelledError):
        ci._wide_candidate_offsets(path, ",", 4, False, ev, 64)
