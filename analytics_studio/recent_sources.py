"""User-level history of successfully imported local files and folders."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any, Mapping

from PySide6.QtCore import QSettings

from analytics_studio.file_import import normalize_options
from analytics_studio.folder_import import normalize_folder_options


DEFAULT_LIMIT = 10
SETTINGS_KEY = "data/recentSources"
SUPPORTED_KINDS = {"csv", "excel", "json", "xml", "parquet", "sqlite", "folder"}


@dataclass(frozen=True)
class RecentSource:
    """One source entry; ``exists`` is checked when the entry is read."""

    path: str
    kind: str
    parser_options: dict[str, Any]
    display_name: str
    exists: bool


class RecentSourcesStore:
    """Bounded, deduplicated MRU stored in user settings, outside project files.

    Call :meth:`add` only after the caller has committed an import. The store
    does not inspect or parse sources; its ``exists`` field lets the UI identify
    paths that disappeared after a successful import.
    """

    def __init__(
        self,
        settings: QSettings | None = None,
        *,
        limit: int = DEFAULT_LIMIT,
        key: str = SETTINGS_KEY,
    ) -> None:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("The recent-source limit must be a positive integer.")
        self._settings = (
            settings if settings is not None
            else QSettings("Analytics Studio", "Analytics Studio")
        )
        self._limit = limit
        self._key = key

    @property
    def sources(self) -> list[RecentSource]:
        """Return most-recent-first entries with existence checked at read time."""
        return [
            RecentSource(
                path=record["path"],
                kind=record["kind"],
                parser_options=dict(record["parser_options"]),
                display_name=record["display_name"],
                exists=Path(record["path"]).exists(),
            )
            for record in self._read_records()
        ]

    def add(
        self,
        path: str | Path,
        kind: str,
        parser_options: Mapping[str, Any] | None = None,
        display_name: str | None = None,
    ) -> None:
        """Record a committed local import, moving its path to the MRU front."""
        normalized_path = _normalize_path(path)
        if not isinstance(kind, str) or kind not in SUPPORTED_KINDS:
            raise ValueError(f"Unsupported recent-source kind {kind!r}.")
        options = _normalize_source_options(kind, parser_options)
        name = display_name.strip() if isinstance(display_name, str) else ""
        if not name:
            name = Path(normalized_path).name

        record = {
            "path": normalized_path,
            "kind": kind,
            "parser_options": options,
            "display_name": name,
        }
        records = [
            item for item in self._read_records()
            if not _same_path(item["path"], normalized_path)
        ]
        self._write_records([record, *records][:self._limit])

    def clear(self) -> None:
        """Remove the recent-source list."""
        self._settings.remove(self._key)
        self._settings.sync()

    def _read_records(self) -> list[dict[str, Any]]:
        raw = self._settings.value(self._key, "")
        if not isinstance(raw, str) or not raw:
            return []
        try:
            decoded = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return []
        if not isinstance(decoded, list):
            return []

        records: list[dict[str, Any]] = []
        for item in decoded:
            if not isinstance(item, dict):
                continue
            path = item.get("path")
            kind = item.get("kind")
            name = item.get("display_name")
            options = item.get("parser_options")
            if not all(isinstance(value, str) and value.strip() for value in (path, kind, name)):
                continue
            if kind not in SUPPORTED_KINDS:
                continue
            try:
                normalized_path = _normalize_path(path)
                normalized_options = _normalize_source_options(kind, options)
            except (TypeError, ValueError, OSError):
                continue
            if any(_same_path(record["path"], normalized_path) for record in records):
                continue
            records.append({
                "path": normalized_path,
                "kind": kind,
                "parser_options": normalized_options,
                "display_name": name,
            })
            if len(records) >= self._limit:
                break
        return records

    def _write_records(self, records: list[dict[str, Any]]) -> None:
        self._settings.setValue(self._key, json.dumps(records, ensure_ascii=False))
        self._settings.sync()


def _normalize_path(path: str | Path) -> str:
    if not isinstance(path, (str, Path)) or not str(path).strip():
        raise ValueError("A recent source needs a local file path.")
    if "://" in str(path):
        raise ValueError("Recent sources must use local paths.")
    expanded = Path(path).expanduser()
    if not expanded.is_absolute():
        expanded = Path.cwd() / expanded
    return str(expanded.resolve(strict=False))


def _normalize_source_options(kind: str, options: Mapping[str, Any] | None) -> dict[str, Any]:
    if kind == "folder":
        return normalize_folder_options(options)
    return normalize_options(kind, options)


def _path_key(path: str) -> str:
    return os.path.normcase(path)


def _same_path(left: str, right: str) -> bool:
    if _path_key(left) == _path_key(right):
        return True
    try:
        return os.path.samefile(left, right)
    except OSError:
        return False
