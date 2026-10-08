"""Bounded local-folder discovery and combine-from-sample-file support."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
import threading
from typing import Any, Callable, Mapping

from analytics_studio.file_import import (
    MAX_CELLS,
    MAX_COLUMNS,
    MAX_DATA_ROWS,
    MAX_SOURCE_BYTES,
    FileImportError,
    ImportCancelledError,
    ImportCandidate,
    default_options,
    normalize_options,
    parse_file,
)


FOLDER_FILE_KINDS = {"csv", "excel", "json", "xml"}
MAX_FOLDER_FILES = 500
MAX_FOLDER_SOURCE_BYTES = 100 * 1024 * 1024


def default_folder_options() -> dict[str, Any]:
    return {
        "file_kind": "csv",
        "recursive": False,
        "name_contains": "",
        "sample_file": "",
        "file_options": default_options("csv"),
        "include_source_name": True,
    }


def normalize_folder_options(options: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Validate the folder filter, sample path, and delegated file parser settings."""
    if options is None:
        supplied: dict[str, Any] = {}
    elif isinstance(options, Mapping):
        supplied = dict(options)
    else:
        raise FileImportError("Folder import options must be an object.")
    result = {**default_folder_options(), **supplied}
    unknown = sorted(map(str, set(supplied) - set(default_folder_options())))
    if unknown:
        raise FileImportError(
            f"Unsupported folder import option(s): {', '.join(map(str, unknown))}."
        )

    kind = result["file_kind"]
    if not isinstance(kind, str) or kind not in FOLDER_FILE_KINDS:
        raise FileImportError("Choose CSV, Excel, JSON, or XML as the folder file type.")
    if not isinstance(result["recursive"], bool):
        raise FileImportError("The include-subfolders setting must be true or false.")
    if not isinstance(result["name_contains"], str) or "\x00" in result["name_contains"]:
        raise FileImportError("The folder filename filter must be text.")
    result["name_contains"] = result["name_contains"].strip()
    if len(result["name_contains"]) > 120:
        raise FileImportError("The folder filename filter cannot exceed 120 characters.")
    if not isinstance(result["include_source_name"], bool):
        raise FileImportError("The source filename column setting must be true or false.")

    sample = result["sample_file"]
    if not isinstance(sample, str) or "\x00" in sample:
        raise FileImportError("Choose a sample file inside the selected folder.")
    sample = sample.replace("\\", "/")
    if sample:
        relative = PurePosixPath(sample)
        if relative.is_absolute() or ".." in relative.parts:
            raise FileImportError("The sample file must be inside the selected folder.")
        sample = relative.as_posix()
    result["sample_file"] = sample
    try:
        result["file_options"] = normalize_options(kind, result["file_options"])
    except (TypeError, ValueError) as exc:
        raise FileImportError(f"The sample file options are invalid: {exc}") from exc
    return result


def discover_folder_files(
    folder: str | Path,
    *,
    file_kind: str,
    recursive: bool = False,
    name_contains: str = "",
    cancel_event: threading.Event | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> list[Path]:
    """Return deterministic, filtered file paths, rejecting unsafe folder sizes."""
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise FileImportError(f"Choose an existing folder: {root}")
    if file_kind not in FOLDER_FILE_KINDS:
        raise FileImportError(f"Unsupported folder file type {file_kind!r}.")

    extensions = {
        "csv": {".csv"},
        "excel": {".xls", ".xlsx", ".xlsm"},
        "json": {".json"},
        "xml": {".xml"},
    }[file_kind]
    query = name_contains.strip().casefold()
    try:
        candidates = root.rglob("*") if recursive else root.iterdir()
        files = []
        scanned = 0
        for candidate in candidates:
            _check_cancelled(cancel_event)
            scanned += 1
            if progress_callback is not None and scanned % 500 == 0:
                progress_callback(f"Scanning folder… {scanned:,} entries checked")
            if not candidate.is_file():
                continue
            relative = candidate.relative_to(root)
            if any(part.startswith(".") for part in relative.parts):
                continue
            filename = candidate.name
            if filename.startswith("~$") or filename.startswith(".~lock."):
                continue
            if candidate.suffix.casefold() not in extensions:
                continue
            if query and query not in filename.casefold():
                continue
            resolved = candidate.resolve()
            try:
                resolved.relative_to(root)
            except ValueError:
                continue
            files.append(resolved)
            if len(files) > MAX_FOLDER_FILES:
                raise FileImportError(
                    f"The folder selection matches more than {MAX_FOLDER_FILES} files. "
                    "Narrow the filename filter or choose a smaller folder."
                )
    except FileImportError:
        raise
    except OSError as exc:
        raise FileImportError(f"Could not list folder {root}: {exc}") from exc

    files.sort(key=lambda path: (path.relative_to(root).as_posix().casefold(), path.as_posix()))
    total_bytes = 0
    for path in files:
        _check_cancelled(cancel_event)
        try:
            total_bytes += path.stat().st_size
        except OSError as exc:
            raise FileImportError(f"Could not read file details for {path.name}: {exc}") from exc
        if total_bytes > MAX_FOLDER_SOURCE_BYTES:
            raise FileImportError(
                f"The matching files exceed the {MAX_FOLDER_SOURCE_BYTES // (1024 * 1024)} MiB "
                "combined folder import limit. Narrow the file filter."
            )
    return files


def parse_folder(
    folder: str | Path,
    options: Mapping[str, Any] | None = None,
    *,
    cancel_event: threading.Event | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> ImportCandidate:
    """Combine matching local files using the selected sample file's schema."""
    root = Path(folder).expanduser().resolve()
    _check_cancelled(cancel_event)
    normalized = normalize_folder_options(options)
    files = discover_folder_files(
        root,
        file_kind=normalized["file_kind"],
        recursive=normalized["recursive"],
        name_contains=normalized["name_contains"],
        cancel_event=cancel_event,
        progress_callback=progress_callback,
    )
    if not files:
        raise FileImportError(
            "No matching files were found. Check the file type, filename filter, and subfolder setting."
        )

    relative_paths = {path.relative_to(root).as_posix(): path for path in files}
    sample_name = normalized["sample_file"] or next(iter(relative_paths))
    sample_path = relative_paths.get(sample_name)
    if sample_path is None:
        raise FileImportError(
            f"The sample file {sample_name!r} is no longer in the filtered folder selection."
        )

    try:
        _report_progress(progress_callback, f"Reading sample file {sample_name}…")
        sample = parse_file(
            sample_path,
            options=normalized["file_options"],
            expected_kind=normalized["file_kind"],
            cancel_event=cancel_event,
            progress_callback=lambda message: _report_progress(
                progress_callback, f"Sample {sample_name}: {message}"
            ),
        )
    except ImportCancelledError:
        raise
    except (OSError, ValueError) as exc:
        raise FileImportError(f"Could not parse sample file {sample_name}: {exc}") from exc
    expected_headers = list(sample.headers)
    source_name_header = _source_name_header(expected_headers)
    headers = ([source_name_header] if normalized["include_source_name"] else []) + expected_headers
    if len(headers) > MAX_COLUMNS:
        raise FileImportError(f"The combined table exceeds the {MAX_COLUMNS:,}-column limit.")

    combined_rows: list[dict[str, str]] = []
    notices: list[str] = []
    for file_index, path in enumerate(files, start=1):
        _check_cancelled(cancel_event)
        relative_name = path.relative_to(root).as_posix()
        try:
            if path == sample_path:
                parsed = sample
            else:
                _report_progress(
                    progress_callback,
                    f"Reading file {file_index:,} of {len(files):,}: {relative_name}…",
                )
                parsed = parse_file(
                    path,
                    options=normalized["file_options"],
                    expected_kind=normalized["file_kind"],
                    cancel_event=cancel_event,
                    progress_callback=lambda message: _report_progress(
                        progress_callback, f"{relative_name}: {message}"
                    ),
                )
        except ImportCancelledError:
            raise
        except (OSError, ValueError) as exc:
            raise FileImportError(f"Could not combine {relative_name}: {exc}") from exc
        if parsed.headers != expected_headers:
            raise FileImportError(
                f"Schema mismatch in {relative_name}. The sample file has columns "
                f"{expected_headers!r}; this file has {parsed.headers!r}. "
                "Filter out the file or use a matching sample file."
            )
        next_row_count = len(combined_rows) + len(parsed.rows)
        if next_row_count > MAX_DATA_ROWS:
            raise FileImportError(
                f"Combined folder data exceeds the {MAX_DATA_ROWS:,}-row import limit."
            )
        if next_row_count * len(headers) > MAX_CELLS:
            raise FileImportError(
                f"Combined folder data exceeds the {MAX_CELLS:,}-cell import limit."
            )
        for row_index, row in enumerate(parsed.rows, start=1):
            if row_index % 5_000 == 0:
                _check_cancelled(cancel_event)
                _report_progress(
                    progress_callback,
                    f"Combining rows from file {file_index:,} of {len(files):,}: "
                    f"{row_index:,} rows processed",
                )
            values = dict(row)
            if normalized["include_source_name"]:
                values[source_name_header] = relative_name
            combined_rows.append(values)
        notices.extend(parsed.notices)

    normalized["sample_file"] = sample_name
    notices.append(f"Combined {len(files):,} files using {sample_name} as the sample schema.")
    if normalized["include_source_name"]:
        notices.append(f"Added {source_name_header!r} to identify each row's source file.")
    _check_cancelled(cancel_event)
    _report_progress(progress_callback, f"Combined {len(files):,} files.")
    return ImportCandidate("folder", headers, combined_rows, normalized, notices)


def _check_cancelled(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise ImportCancelledError("Import canceled.")


def _report_progress(
    progress_callback: Callable[[str], None] | None,
    message: str,
) -> None:
    if progress_callback is not None:
        progress_callback(message)


def _source_name_header(headers: list[str]) -> str:
    base = "Source.Name"
    name = base
    suffix = 2
    while name in headers:
        name = f"{base}_{suffix}"
        suffix += 1
    return name
