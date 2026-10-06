"""Versioned, human-readable project files and crash-safe persistence."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any
from uuid import uuid4


FORMAT_ID = "com.analytics-studio.project"
FORMAT_VERSION = 2
SUPPORTED_VIEWS = {"Report", "Data", "Model"}
SUPPORTED_FILE_KINDS = {"csv", "excel", "json", "xml"}


class ProjectFileError(Exception):
    """A project file is unreadable or does not match its documented schema."""


class UnsupportedProjectVersion(ProjectFileError):
    """The project was written by a format version this app cannot read."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def new_project(name: str = "Untitled Project") -> dict[str, Any]:
    page_id = str(uuid4())
    now = utc_now()
    return {
        "format": FORMAT_ID,
        "format_version": FORMAT_VERSION,
        "project_id": str(uuid4()),
        "name": name,
        "created_at": now,
        "modified_at": now,
        "active_view": "Report",
        "active_source_id": None,
        "data_sources": [],
        "report": {
            "pages": [{
                "id": page_id,
                "name": "Overview",
                "visuals": ["Revenue KPI", "Cost KPI", "Margin KPI", "Units KPI", "Orders KPI", "Monthly revenue", "Region revenue"],
            }],
            "active_page_id": page_id,
            "chart_types": {"monthly": "column", "region": "bar"},
        },
        "model": {"tables": [], "relationships": []},
    }


def validate_project(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProjectFileError("The project root must be a JSON object.")
    if value.get("format") != FORMAT_ID:
        raise ProjectFileError("This file is not an Analytics Studio project.")

    version = value.get("format_version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise ProjectFileError("The project has no valid format_version.")
    if version > FORMAT_VERSION:
        raise UnsupportedProjectVersion(
            f"This project uses format version {version}; this app supports up to {FORMAT_VERSION}."
        )
    if version == 1:
        value = _migrate_v1_to_v2(value)
    elif version == FORMAT_VERSION:
        value = deepcopy(value)
    else:
        raise UnsupportedProjectVersion(f"Project format version {version} is not supported.")

    for key in ("project_id", "name", "created_at", "modified_at"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise ProjectFileError(f"The project field {key!r} must be a non-empty string.")
    active_view = value.get("active_view")
    if not isinstance(active_view, str) or active_view not in SUPPORTED_VIEWS:
        raise ProjectFileError("The project active_view must be Report, Data, or Model.")

    sources = value.get("data_sources")
    if not isinstance(sources, list):
        raise ProjectFileError("The project data_sources field must be a list.")
    source_ids: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            raise ProjectFileError("Each data source must be a JSON object.")
        for key in ("id", "name", "kind", "path"):
            if not isinstance(source.get(key), str) or not source[key].strip():
                raise ProjectFileError(f"Each data source needs a non-empty {key!r} field.")
        if "\x00" in source["path"]:
            raise ProjectFileError("A data source path contains an invalid character.")
        if source["id"] in source_ids:
            raise ProjectFileError(f"Data source ID {source['id']!r} is duplicated.")
        source_ids.add(source["id"])

    active_source_id = value.get("active_source_id")
    if active_source_id is not None and (
        not isinstance(active_source_id, str)
        or not active_source_id.strip()
        or not any(source.get("id") == active_source_id for source in sources)
    ):
        raise ProjectFileError("The active_source_id must be null or match an existing data source.")

    # Add defaults for early v2 documents that omit options. Validate and canonicalize
    # persisted settings so refresh and reopen interpret the source consistently.
    from analytics_studio.file_import import default_options, normalize_options

    for source in sources:
        if source.get("kind") not in SUPPORTED_FILE_KINDS:
            continue
        options = source.get("parser_options", default_options(source["kind"]))
        try:
            source["parser_options"] = normalize_options(source["kind"], options)
        except (TypeError, ValueError) as exc:
            raise ProjectFileError(
                f"The parser_options for data source {source['id']!r} are invalid: {exc}"
            ) from exc

    report = value.get("report")
    pages = report.get("pages") if isinstance(report, dict) else None
    if not isinstance(pages, list) or not pages:
        raise ProjectFileError("A project must contain at least one report page.")
    page_ids: set[str] = set()
    for page in pages:
        if not isinstance(page, dict):
            raise ProjectFileError("Each report page must be a JSON object.")
        page_id = page.get("id")
        if not isinstance(page_id, str) or not page_id.strip() or page_id in page_ids:
            raise ProjectFileError("Report page IDs must be non-empty and unique.")
        page_ids.add(page_id)
        if not isinstance(page.get("name"), str) or not page["name"].strip():
            raise ProjectFileError("Each report page needs a non-empty name.")
        visuals = page.get("visuals")
        if not isinstance(visuals, list) or any(not isinstance(item, str) for item in visuals):
            raise ProjectFileError("A report page visuals field must be a list of strings.")
    active_page_id = report.get("active_page_id")
    if not isinstance(active_page_id, str) or active_page_id not in page_ids:
        raise ProjectFileError("The report active_page_id must match an existing page.")
    chart_types = report.get("chart_types")
    if (
        not isinstance(chart_types, dict)
        or not isinstance(chart_types.get("monthly"), str)
        or chart_types.get("monthly") not in {"column", "bar", "line"}
        or not isinstance(chart_types.get("region"), str)
        or chart_types.get("region") not in {"column", "bar", "line"}
    ):
        raise ProjectFileError("The report chart_types must define monthly and region chart types.")

    model = value.get("model")
    if not isinstance(model, dict):
        raise ProjectFileError("The project model field must be an object.")
    for key in ("tables", "relationships"):
        if not isinstance(model.get(key), list):
            raise ProjectFileError(f"The project model {key!r} field must be a list.")
    for table in model["tables"]:
        if not isinstance(table, dict) or not isinstance(table.get("name"), str):
            raise ProjectFileError("Each model table must have a name.")
    for relationship in model["relationships"]:
        if (
            not isinstance(relationship, dict)
            or not isinstance(relationship.get("from"), str)
            or not isinstance(relationship.get("to"), str)
        ):
            raise ProjectFileError("Each model relationship must define string from and to values.")

    return deepcopy(value)


def _migrate_v1_to_v2(value: dict[str, Any]) -> dict[str, Any]:
    """Convert v1 in memory, preserving its first CSV/Excel source selection rule."""
    from analytics_studio.file_import import default_options

    migrated = deepcopy(value)
    sources = migrated.get("data_sources")
    if not isinstance(sources, list):
        sources = []
    active = next(
        (source for source in sources
         if isinstance(source, dict) and source.get("kind") in {"csv", "excel"}),
        None,
    )
    migrated["active_source_id"] = active.get("id") if active else None
    for source in sources:
        if isinstance(source, dict) and source.get("kind") in SUPPORTED_FILE_KINDS:
            source.setdefault("parser_options", default_options(source["kind"]))
    migrated["format_version"] = 2
    return migrated


def _read_project(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProjectFileError(f"Could not read {path.name}: {exc}") from exc
    return validate_project(value)


def load_project(path: Path) -> tuple[dict[str, Any], bool]:
    """Load a project, falling back to its last known-good .bak after corruption."""
    path = Path(path)
    try:
        return _read_project(path), False
    except UnsupportedProjectVersion:
        # Do not silently replace a newer project with an older backup.
        raise
    except (ProjectFileError, FileNotFoundError) as primary_error:
        backup = Path(f"{path}.bak")
        if not backup.is_file():
            raise ProjectFileError(f"{primary_error} No recovery backup was found.") from primary_error
        try:
            return _read_project(backup), True
        except (ProjectFileError, FileNotFoundError) as backup_error:
            raise ProjectFileError(
                f"The project could not be opened ({primary_error}); its recovery copy also failed ({backup_error})."
            ) from backup_error


def _atomic_write(path: Path, contents: str) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
        if os.name == "posix":
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        temp_path.unlink(missing_ok=True)


def save_project(
    path: Path,
    document: dict[str, Any],
    *,
    recovered_from_backup: bool = False,
) -> dict[str, Any]:
    """Atomically save JSON and keep the previous good file as ``<name>.bak``."""
    path = Path(path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    value = validate_project(document)
    value["modified_at"] = utc_now()
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"

    backup = Path(f"{path}.bak")
    if path.is_file() and not recovered_from_backup:
        fd, backup_temp_name = tempfile.mkstemp(
            prefix=f".{backup.name}.", suffix=".tmp", dir=backup.parent
        )
        os.close(fd)
        backup_temp = Path(backup_temp_name)
        try:
            shutil.copy2(path, backup_temp)
            with backup_temp.open("rb") as stream:
                os.fsync(stream.fileno())
            os.replace(backup_temp, backup)
        finally:
            backup_temp.unlink(missing_ok=True)

    _atomic_write(path, payload)
    return value


def source_path_for_save(source_path: Path, project_path: Path) -> str:
    """Store linked data relative to the project when it is inside that folder."""
    source_path = Path(source_path).expanduser().resolve()
    project_dir = Path(project_path).expanduser().resolve().parent
    try:
        return source_path.relative_to(project_dir).as_posix()
    except ValueError:
        return str(source_path)


def resolve_source_path(stored_path: str, project_path: Path) -> Path:
    path = Path(stored_path).expanduser()
    if not path.is_absolute():
        path = Path(project_path).expanduser().resolve().parent / path
    return path.resolve()
