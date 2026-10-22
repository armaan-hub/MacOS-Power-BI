"""Validation helpers for local model relationship metadata."""

from __future__ import annotations

import re
from collections import defaultdict, deque
from copy import deepcopy
from datetime import date, datetime, time
from decimal import Decimal, DecimalException
from typing import Any
from uuid import uuid4

from analytics_studio.power_query_values import cell_to_text, is_cell_error


RELATIONSHIP_VERSION = 1
RELATIONSHIP_CARDINALITIES = {
    "one_to_one",
    "one_to_many",
    "many_to_one",
    "many_to_many",
}
RELATIONSHIP_FILTER_DIRECTIONS = {"single", "both"}
_STRUCTURED_FIELDS = {
    "relationship_version",
    "id",
    "from",
    "to",
    "from_table_id",
    "from_column",
    "to_table_id",
    "to_column",
    "cardinality",
    "cross_filter_direction",
    "is_active",
}


class RelationshipError(ValueError):
    """A relationship definition is invalid or cannot be used with loaded data."""


def relationship_filter_directions(relationship: dict[str, Any]) -> tuple[str, ...]:
    """Return the active filter edge directions for a saved or temporary link."""
    override = relationship.get("filter_direction_override")
    if override == "none":
        return ()
    if override == "both":
        return ("from_to", "to_from")
    if override in {"from_to", "to_from"}:
        return (str(override),)
    if relationship.get("cross_filter_direction") == "both":
        return ("from_to", "to_from")
    if relationship.get("cardinality") in {"many_to_one", "many_to_many"}:
        return ("to_from",)  # live Power BI: a single-direction many-to-many filters From by To, like many-to-one
    return ("from_to",)


def propagate_relationship_filters(
    tables: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    filter_table_ids: set[str],
    unknown_selected: dict[str, bool] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Propagate explicitly filtered rows across active, loaded relationships.

    unknown_selected: for the filtered tables whose virtual blank member (the "unknown member" that collects the rows of a
    related table whose key is BLANK or has no match) is still selected by their own filters. Rows of a table on the other
    side of the relationship whose key has no match in the one-side table are reached through that member (live Power BI:
    CALCULATE(SUM(Fact[Amt]), Dim[Cat] <> "A") keeps the facts of unknown products). A filtered table missing from the
    mapping, or mapped to True, selects it; a table narrowed by another table's filter keeps it only while a visible row of
    that table is such an orphan."""
    tables_by_id: dict[str, dict[str, Any]] = {}
    rows_by_id: dict[str, list[dict[str, Any]]] = {}
    for table in tables:
        table_id = table.get("id")
        if not isinstance(table_id, str) or not table_id:
            raise RelationshipError("A loaded model table is missing its ID.")
        if table_id in tables_by_id:
            raise RelationshipError("Loaded model table IDs must be unique.")
        if not isinstance(table.get("headers"), list) or not isinstance(table.get("rows"), list):
            raise RelationshipError(f"Loaded table {table.get('name', table_id)!r} is incomplete.")
        if "filter_rows" in table and not isinstance(table["filter_rows"], list):
            raise RelationshipError(f"Loaded table {table.get('name', table_id)!r} has an invalid filter context.")
        tables_by_id[table_id] = table
        rows_by_id[table_id] = list(table["rows"])

    for table_id in filter_table_ids:
        table = tables_by_id.get(table_id)
        if table is not None and "filter_rows" in table:
            rows_by_id[table_id] = list(table["filter_rows"])

    edges_by_source: dict[str, list[tuple[str, str, str, str, str, str]]] = defaultdict(list)

    def add_edge(
        source_id: str,
        source_column: str,
        target_id: str,
        target_column: str,
        source_role: str = "peer",
    ) -> None:
        source_table = tables_by_id[source_id]
        target_table = tables_by_id[target_id]
        if source_column not in source_table["headers"] or target_column not in target_table["headers"]:
            raise RelationshipError("An active relationship refers to a column that is no longer loaded.")
        source_type = str(source_table.get("column_types", {}).get(source_column, "text"))
        target_type = str(target_table.get("column_types", {}).get(target_column, "text"))
        compatible = (
            source_type == target_type
            or "any" in {source_type, target_type}
            or {source_type, target_type} <= {
            "whole_number", "decimal_number",
            }
        )
        if not compatible:
            raise RelationshipError("An active relationship has incompatible column types.")
        edges_by_source[source_id].append(
            (target_id, source_column, target_column, source_type, target_type, source_role)
        )

    def validate_unique_key(table_id: str, column: str) -> None:
        table = tables_by_id[table_id]
        column_type = str(table.get("column_types", {}).get(column, "text"))
        seen: set[tuple[str, Any]] = set()
        for row in table["rows"]:
            key = _relationship_value_key(row.get(column), column_type)
            if key in seen:
                raise RelationshipError(
                    f"{table.get('name', table_id)}[{column}] no longer has unique values "
                    "for the relationship's one side."
                )
            seen.add(key)

    for relationship in relationships:
        if (
            not isinstance(relationship, dict)
            or type(relationship.get("relationship_version")) is not int
            or relationship.get("relationship_version") != RELATIONSHIP_VERSION
            or not relationship.get("is_active")
        ):
            continue
        from_id = str(relationship.get("from_table_id", ""))
        to_id = str(relationship.get("to_table_id", ""))
        # Keep saved links for currently unloaded sources, but do not use them
        # until both endpoints are available in the model context.
        if from_id not in tables_by_id or to_id not in tables_by_id:
            continue
        from_column = str(relationship["from_column"])
        to_column = str(relationship["to_column"])
        if (
            from_column not in tables_by_id[from_id]["headers"]
            or to_column not in tables_by_id[to_id]["headers"]
        ):
            raise RelationshipError("An active relationship refers to a column that is no longer loaded.")
        cardinality = relationship.get("cardinality")
        if cardinality in {"one_to_one", "one_to_many"}:
            validate_unique_key(from_id, from_column)
        if cardinality in {"one_to_one", "many_to_one"}:
            validate_unique_key(to_id, to_column)
        filter_directions = relationship_filter_directions(relationship)
        # the blank member exists on the one side of a one-to-many relationship; one-to-one and many-to-many ends are peers
        from_role = "one" if cardinality == "one_to_many" else "many" if cardinality == "many_to_one" else "peer"
        to_role = "one" if cardinality == "many_to_one" else "many" if cardinality == "one_to_many" else "peer"
        if "from_to" in filter_directions:
            add_edge(from_id, from_column, to_id, to_column, from_role)
        if "to_from" in filter_directions:
            add_edge(to_id, to_column, from_id, from_column, to_role)

    filter_roots = {table_id for table_id in filter_table_ids if table_id in tables_by_id}
    for root_id in sorted(
        filter_roots,
        key=lambda item: str(tables_by_id[item].get("name", item)).casefold(),
    ):
        paths_by_target: dict[str, tuple[str, ...]] = {root_id: (root_id,)}
        paths = deque([(root_id, (root_id,))])
        while paths:
            source_id, path = paths.popleft()
            for edge in edges_by_source.get(source_id, []):
                target_id = edge[0]
                if target_id in path:
                    continue
                next_path = (*path, target_id)
                previous_path = paths_by_target.get(target_id)
                if previous_path is not None:
                    def describe_path(table_path: tuple[str, ...]) -> str:
                        return " → ".join(
                            str(tables_by_id[item].get("name", item))
                            for item in table_path
                        )

                    raise RelationshipError(
                        f"Ambiguous active relationship paths from "
                        f"{tables_by_id[root_id].get('name', root_id)!r} to "
                        f"{tables_by_id[target_id].get('name', target_id)!r}: "
                        f"{describe_path(previous_path)}; {describe_path(next_path)}. "
                        "Remove or deactivate one relationship path."
                    )
                paths_by_target[target_id] = next_path
                paths.append((target_id, next_path))

    constrained = deque(filter_roots)
    constrained_ids = set(constrained)
    # does the virtual blank member of a constrained table survive the constraints so far?
    unknown_state: dict[str, bool] = {
        root_id: (unknown_selected or {}).get(root_id, True) for root_id in filter_roots
    }
    all_key_cache: dict[tuple[str, str], set[tuple[str, Any]]] = {}

    def all_keys(table_id: str, column: str, column_type: str) -> set[tuple[str, Any]]:
        cached = all_key_cache.get((table_id, column))
        if cached is None:
            cached = {_relationship_value_key(row.get(column), column_type) for row in tables_by_id[table_id]["rows"]}
            all_key_cache[(table_id, column)] = cached
        return cached

    narrowed_by: dict[str, set[str]] = defaultdict(set)  # which tables narrowed a table (a filter never echoes back to its origin)
    while constrained:
        source_id = constrained.popleft()
        for target_id, source_column, target_column, source_type, target_type, source_role in edges_by_source.get(source_id, []):
            if source_id not in filter_roots and narrowed_by[source_id] <= {target_id}:
                continue  # live Power BI: no round trip - a table only filtered by its neighbour does not filter that neighbour back
            narrowed_by[target_id].add(source_id)
            source_keys = {
                _relationship_value_key(row.get(source_column), source_type)
                for row in rows_by_id[source_id]
            }
            current_target_rows = rows_by_id[target_id]
            if source_role == "one" and unknown_state.get(source_id, True):
                known = all_keys(source_id, source_column, source_type)
                filtered_target_rows = [
                    row for row in current_target_rows
                    if (key := _relationship_value_key(row.get(target_column), target_type)) in source_keys or key not in known
                ]
            else:
                filtered_target_rows = [
                    row for row in current_target_rows
                    if _relationship_value_key(row.get(target_column), target_type) in source_keys
                ]
            changed = len(filtered_target_rows) != len(current_target_rows)
            if changed:
                rows_by_id[target_id] = filtered_target_rows
            if source_role == "one":  # the blank member of the filtered table relates to the blank member of its source only
                before = unknown_state.get(target_id, True)
                after = before and unknown_state.get(source_id, True)
                if after != before or target_id not in unknown_state:
                    unknown_state[target_id] = after
                    changed = changed or after != before
            elif source_role == "many":  # the many side filters its one side: the blank member stays only while a visible row is an orphan
                known = all_keys(target_id, target_column, target_type)
                orphan_visible = any(
                    _relationship_value_key(row.get(source_column), source_type) not in known
                    for row in rows_by_id[source_id]
                )
                before = unknown_state.get(target_id, True)
                after = before and orphan_visible
                if after != before or target_id not in unknown_state:
                    unknown_state[target_id] = after
                    changed = changed or after != before
            if target_id not in constrained_ids or changed:
                constrained_ids.add(target_id)
                constrained.append(target_id)

    return rows_by_id


def _relationship_value_key(value: Any, column_type: str) -> tuple[str, Any]:
    if is_cell_error(value):
        raise RelationshipError(
            "A relationship key contains a Power Query cell error; remove or replace the error first."
        )
    if value is None:
        return "null", None
    if isinstance(value, str) and value == "":
        return "empty", ""
    if column_type == "any" and isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        try:
            number = Decimal(str(value))
        except DecimalException as exc:
            raise RelationshipError("A relationship key contains a value that is not numeric.") from exc
        if not number.is_finite():
            raise RelationshipError("A relationship key contains a value that is not finite.")
        return "number", number
    if column_type in {"whole_number", "decimal_number"}:
        if isinstance(value, bool):
            raise RelationshipError("A relationship key contains a value that does not match its model type.")
        try:
            number = Decimal(cell_to_text(value))
        except DecimalException as exc:
            raise RelationshipError("A relationship key contains a value that is not numeric.") from exc
        if not number.is_finite() or (
            column_type == "whole_number" and number != number.to_integral_value()
        ):
            raise RelationshipError("A relationship key contains a value that does not match its model type.")
        return "number", number
    if column_type == "boolean":
        if isinstance(value, bool):
            return "boolean", value
        if isinstance(value, str) and value.casefold() in {"true", "false"}:
            return "boolean", value.casefold() == "true"
        raise RelationshipError("A relationship key contains a value that does not match its model type.")
    if isinstance(value, bool):
        return "boolean", value
    if isinstance(value, datetime):
        return "datetime", value.isoformat()
    if isinstance(value, date):
        return "date", value.isoformat()
    if isinstance(value, time):
        return "time", value.isoformat()
    if isinstance(value, str):
        # Power BI's model engine compares text without case and trims trailing
        # spaces while retaining leading spaces. The local project has no
        # persisted collation setting, so mirror the documented common case.
        normalized = value.rstrip(" ")
        if normalized == "":
            return "empty", ""
        return "value", normalized.casefold()
    # Keep uncommon local scalar representations on the same shared comparer
    # path used by relationship joins, uniqueness, and RELATED lookups.
    return "value", cell_to_text(value).casefold()


def unknown_member_table_ids(
    tables: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    visible_rows_by_id: dict[str, list[dict[str, Any]]] | None = None,
) -> set[str]:
    """Return tables with a visible relationship-generated blank member."""
    tables_by_id = {str(table.get("id", "")): table for table in tables}
    visible_rows_by_id = visible_rows_by_id or {}
    unknown_tables: set[str] = set()
    for relationship in relationships:
        if (
            not isinstance(relationship, dict)
            or type(relationship.get("relationship_version")) is not int
            or relationship.get("relationship_version") != RELATIONSHIP_VERSION
        ):
            continue
        cardinality = relationship.get("cardinality")
        if cardinality == "one_to_many":
            parent_id, parent_column = (
                str(relationship.get("from_table_id", "")),
                str(relationship.get("from_column", "")),
            )
            child_id, child_column = (
                str(relationship.get("to_table_id", "")),
                str(relationship.get("to_column", "")),
            )
        elif cardinality == "many_to_one":
            parent_id, parent_column = (
                str(relationship.get("to_table_id", "")),
                str(relationship.get("to_column", "")),
            )
            child_id, child_column = (
                str(relationship.get("from_table_id", "")),
                str(relationship.get("from_column", "")),
            )
        elif cardinality == "one_to_one":
            from_id = str(relationship.get("from_table_id", ""))
            to_id = str(relationship.get("to_table_id", ""))
            from_column = str(relationship.get("from_column", ""))
            to_column = str(relationship.get("to_column", ""))
            from_table = tables_by_id.get(from_id)
            to_table = tables_by_id.get(to_id)
            if from_table is None or to_table is None:
                continue
            if from_column not in from_table.get("headers", []) or to_column not in to_table.get("headers", []):
                continue
            from_type = str(from_table.get("column_types", {}).get(from_column, "text"))
            to_type = str(to_table.get("column_types", {}).get(to_column, "text"))
            all_from_keys = {
                _relationship_value_key(row.get(from_column), from_type)
                for row in from_table["rows"]
            }
            all_to_keys = {
                _relationship_value_key(row.get(to_column), to_type)
                for row in to_table["rows"]
            }
            relationship_is_active = bool(relationship.get("is_active"))
            directions = relationship_filter_directions(relationship)
            from_can_filter_to = (
                relationship_is_active and "from_to" in directions
            )
            to_can_filter_from = (
                relationship_is_active and "to_from" in directions
            )
            visible_from_keys = {
                _relationship_value_key(row.get(from_column), from_type)
                for row in (
                    visible_rows_by_id.get(from_id, from_table["rows"])
                    if from_can_filter_to
                    else from_table["rows"]
                )
            }
            visible_to_keys = {
                _relationship_value_key(row.get(to_column), to_type)
                for row in (
                    visible_rows_by_id.get(to_id, to_table["rows"])
                    if to_can_filter_from
                    else to_table["rows"]
                )
            }
            if visible_from_keys - all_to_keys:
                unknown_tables.add(to_id)
            if visible_to_keys - all_from_keys:
                unknown_tables.add(from_id)
            continue
        else:
            continue
        parent = tables_by_id.get(parent_id)
        child = tables_by_id.get(child_id)
        if parent is None or child is None:
            continue
        if parent_column not in parent.get("headers", []) or child_column not in child.get("headers", []):
            continue
        parent_type = str(parent.get("column_types", {}).get(parent_column, "text"))
        child_type = str(child.get("column_types", {}).get(child_column, "text"))
        parent_keys = {
            _relationship_value_key(row.get(parent_column), parent_type)
            for row in parent["rows"]
        }
        child_rows = child["rows"]
        directions = relationship_filter_directions(relationship)
        child_filters_parent = (
            cardinality == "one_to_many" and "to_from" in directions
        ) or (
            cardinality == "many_to_one" and "from_to" in directions
        )
        if relationship.get("is_active") and child_filters_parent:
            child_rows = visible_rows_by_id.get(child_id, child_rows)
        if any(
            _relationship_value_key(row.get(child_column), child_type) not in parent_keys
            for row in child_rows
        ):
            unknown_tables.add(parent_id)
    return unknown_tables


def normalize_relationships(
    relationships: Any,
    table_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Validate new definitions while retaining older display-only metadata."""
    if not isinstance(relationships, list):
        raise RelationshipError("Model relationships must be a list.")
    table_ids: set[str] = set()
    for table in table_records:
        if not isinstance(table, dict):
            continue
        for key in ("id", "source_id"):
            value = table.get(key)
            if isinstance(value, str) and value:
                table_ids.add(value)

    result: list[dict[str, Any]] = []
    ids: set[str] = set()
    endpoint_pairs: set[tuple[tuple[str, str], tuple[str, str]]] = set()
    active_table_pairs: set[tuple[str, str]] = set()
    for relationship in relationships:
        if (
            not isinstance(relationship, dict)
            or not isinstance(relationship.get("from"), str)
            or not isinstance(relationship.get("to"), str)
        ):
            raise RelationshipError("Each relationship must define string from and to references.")
        if "relationship_version" not in relationship:
            # Older projects only stored descriptive endpoint strings.
            result.append(deepcopy(relationship))
            continue
        if set(relationship) != _STRUCTURED_FIELDS:
            raise RelationshipError("A structured relationship has missing or unknown fields.")
        version = relationship.get("relationship_version")
        if type(version) is not int or version != RELATIONSHIP_VERSION:
            raise RelationshipError("This relationship metadata version is not supported.")

        relationship_id = relationship.get("id")
        if (
            not isinstance(relationship_id, str)
            or not relationship_id.strip()
            or len(relationship_id) > 128
            or any(ord(char) < 32 for char in relationship_id)
            or relationship_id in ids
        ):
            raise RelationshipError("Relationship IDs must be non-empty and unique.")
        ids.add(relationship_id)

        from_table_id = relationship.get("from_table_id")
        to_table_id = relationship.get("to_table_id")
        from_column = relationship.get("from_column")
        to_column = relationship.get("to_column")
        if (
            not isinstance(from_table_id, str)
            or from_table_id not in table_ids
            or not isinstance(to_table_id, str)
            or to_table_id not in table_ids
            or from_table_id == to_table_id
        ):
            raise RelationshipError("A relationship must connect two different model tables.")
        if not _valid_column_name(from_column) or not _valid_column_name(to_column):
            raise RelationshipError("Relationship columns must have valid non-empty names.")
        if (
            not relationship["from"].strip()
            or len(relationship["from"]) > 512
            or not relationship["to"].strip()
            or len(relationship["to"]) > 512
        ):
            raise RelationshipError("Relationship endpoint labels must be non-empty and bounded.")
        cardinality = relationship.get("cardinality")
        if not isinstance(cardinality, str) or cardinality not in RELATIONSHIP_CARDINALITIES:
            raise RelationshipError("Choose a supported relationship cardinality.")
        filter_direction = relationship.get("cross_filter_direction")
        if (
            not isinstance(filter_direction, str)
            or filter_direction not in RELATIONSHIP_FILTER_DIRECTIONS
        ):
            raise RelationshipError("Choose Single or Both for the cross-filter direction.")
        if not isinstance(relationship.get("is_active"), bool):
            raise RelationshipError("The relationship active setting must be true or false.")

        endpoints = tuple(sorted((
            (from_table_id, from_column),
            (to_table_id, to_column),
        )))
        if endpoints in endpoint_pairs:
            raise RelationshipError("A relationship already exists between those two columns.")
        endpoint_pairs.add(endpoints)
        if relationship["is_active"]:
            table_pair = tuple(sorted((from_table_id, to_table_id)))
            if table_pair in active_table_pairs:
                raise RelationshipError(
                    "Only one relationship between a pair of tables can be active."
                )
            active_table_pairs.add(table_pair)
        result.append(deepcopy(relationship))
    return result


def _valid_column_name(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value) <= 256
        and not any(ord(char) < 32 for char in value)
    )


_AUTO_RELATIONSHIP_KEY_WORDS = {"id", "key", "code", "pk", "fk"}
_AUTO_RELATIONSHIP_NOISE_WORDS = {"name", *_AUTO_RELATIONSHIP_KEY_WORDS}
# DetectionHelper's compiled patterns and split delimiters are recovered from
# its shipped managed metadata. Keep these aligned with its key-name pass.
_AUTO_RELATIONSHIP_COMMENT_REGEX = re.compile(r"\([^\(//)]*\)")
_AUTO_RELATIONSHIP_NUMBER_REGEX = re.compile(r"[0-9]")
_AUTO_RELATIONSHIP_CAMEL_REGEX = re.compile(r"[A-Z]([a-z]+|[A-Z]*$)")
_AUTO_RELATIONSHIP_NAME_DELIMITERS = frozenset(
    " `~!@#$%^&*()_-+=[{}]|\\:;\"',<.>/?"
)
# GetRelationshipKeyType keeps date, datetime, and time distinct; it maps
# decimal Number to Double and Variant to InvalidKey. Our local model's `any`
# also has no key type, so it is deliberately ineligible.
_AUTO_RELATIONSHIP_KEY_TYPES = {
    "text": "string",
    "whole_number": "int",
    "decimal_number": "double",
}


def detect_relationship_candidates(
    tables: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    tables_to_be_connected: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Suggest reviewable single-column relationships from names and loaded values.

    Power BI's managed modeler exposes literal and normalized key passes,
    String/Int/Double eligibility, discovery-ordered key groups, cardinality-led
    primary-key priority, per-key candidate caps, and an optional scoped
    path-length pass. This local proposal flow mirrors those static observations
    where the model carries the needed data; the caller still lets the user
    review each suggestion.
    """
    eligible = []
    seen_ids: set[str] = set()
    for table in tables:
        table_id = table.get("id")
        headers = table.get("headers")
        rows = table.get("rows")
        if (
            not isinstance(table_id, str)
            or not table_id
            or table_id in seen_ids
            or not isinstance(headers, list)
            or not isinstance(rows, list)
            or not rows
        ):
            continue
        seen_ids.add(table_id)
        eligible.append(table)
    if len(eligible) < 2:
        return []

    calculated_names_by_table: dict[str, set[str]] = {}
    for table in eligible:
        raw_calculated_columns = table.get("calculated_columns", [])
        if not isinstance(raw_calculated_columns, list):
            calculated_names_by_table[str(table["id"])] = set()
            continue
        calculated_names: set[str] = set()
        for item in raw_calculated_columns:
            if isinstance(item, str):
                calculated_names.add(item.casefold())
            elif isinstance(item, dict) and isinstance(item.get("name"), str):
                calculated_names.add(item["name"].casefold())
        calculated_names_by_table[str(table["id"])] = calculated_names

    existing_table_pairs: set[tuple[str, str]] = set()
    saved_relationship_pairs: list[tuple[str, str]] = []
    existing_relationship_roles: list[tuple[str, str, str, str, str]] = []
    filter_graph_relationships: list[dict[str, Any]] = []

    # Preserve the saved relationship sequence: the target enumerates
    # IDataModel.Relationships directly, and this project's editor appends new
    # relationships while project normalization retains list order.
    for relationship in relationships:
        if (
            not isinstance(relationship, dict)
            or relationship.get("relationship_version") != RELATIONSHIP_VERSION
        ):
            continue
        from_id = relationship.get("from_table_id")
        to_id = relationship.get("to_table_id")
        if not isinstance(from_id, str) or not isinstance(to_id, str) or from_id == to_id:
            continue
        filter_graph_relationships.append(relationship)
        existing_table_pairs.add(tuple(sorted((from_id, to_id))))
        saved_relationship_pairs.append((from_id, to_id))
        from_column = relationship.get("from_column")
        to_column = relationship.get("to_column")
        cardinality = relationship.get("cardinality")
        if (
            isinstance(from_column, str)
            and isinstance(to_column, str)
            and isinstance(cardinality, str)
        ):
            existing_relationship_roles.append(
                (from_id, from_column, to_id, to_column, cardinality)
            )
    saved_table_pairs = set(existing_table_pairs)

    def split_key_words(value: Any, noise_words: set[str] | None) -> tuple[str, ...]:
        text = str(value or "")
        # The shipped MatchEvaluator prepends a space to each CamelRegex match.
        text = _AUTO_RELATIONSHIP_CAMEL_REGEX.sub(
            lambda match: f" {match.group(0)}", text
        )
        split_text = "".join(
            " " if char in _AUTO_RELATIONSHIP_NAME_DELIMITERS else char
            for char in text
        )
        return tuple(
            normalized_word
            for word in split_text.split(" ")
            if word
            for normalized_word in (word.lower(),)
            if noise_words is None or normalized_word not in noise_words
        )

    key_cache: dict[tuple[str, str, bool], tuple[str, ...]] = {}

    def column_key_tokens(
        table: dict[str, Any], column: str, normalized_pass: bool
    ) -> tuple[str, ...]:
        cache_key = (str(table["id"]), column, normalized_pass)
        if cache_key in key_cache:
            return key_cache[cache_key]

        column_name = column
        table_name = str(table.get("name") or "")
        if normalized_pass:
            # GetColumnKey's second pass removes comments/digits and unwraps
            # dot-qualified column names to their final column/table segments.
            column_name = _AUTO_RELATIONSHIP_NUMBER_REGEX.sub("", column_name)
            column_name = _AUTO_RELATIONSHIP_COMMENT_REGEX.sub("", column_name)
            qualified_parts = column_name.split(".")
            if len(qualified_parts) >= 2:
                column_name, table_name = qualified_parts[-1], qualified_parts[-2]
            key_words = split_key_words(column_name, _AUTO_RELATIONSHIP_NOISE_WORDS)
        else:
            key_words = split_key_words(column_name, None)

        if not key_words:
            key_words = split_key_words(table_name, None)
        key_cache[cache_key] = key_words
        return key_words

    def is_usable_key(key: tuple[str, ...]) -> bool:
        # GetColumnsByKey excludes keys whose complete name is a noise word
        # (for example, a literal "ID" column). The normalized pass can still
        # recover a table-name key for an ID-only column.
        return bool(key) and not (
            len(key) == 1 and key[0] in _AUTO_RELATIONSHIP_NOISE_WORDS
        )

    def types_compatible(left: str, right: str) -> bool:
        left_key_type = _AUTO_RELATIONSHIP_KEY_TYPES.get(left)
        return (
            left_key_type is not None
            and left_key_type == _AUTO_RELATIONSHIP_KEY_TYPES.get(right)
        )

    # GetColumnsByKey increments its per-table key counter before checking
    # `count >= 30`, so the 30th column for a table/key is omitted. It then
    # increments a second counter for each key-group with the same distinct
    # table-name signature and omits groups after the 30th.
    max_columns_per_table_key = 30
    max_key_groups_per_table_signature = 30
    key_groups_by_pass: dict[
        bool, list[tuple[tuple[str, ...], list[tuple[dict[str, Any], str]]]]
    ] = {}
    for normalized_pass in (False, True):
        columns_by_key: dict[
            tuple[str, ...], list[tuple[dict[str, Any], str]]
        ] = {}
        columns_per_table_key: dict[tuple[str, tuple[str, ...]], int] = {}
        for table in eligible:
            table_id = str(table["id"])
            table_types = table.get("column_types", {})
            group_by_columns = table.get("group_by_columns", {})
            for raw_column in table["headers"]:
                column = str(raw_column)
                if column.casefold() in calculated_names_by_table[table_id]:
                    continue
                if (
                    isinstance(group_by_columns, dict)
                    and group_by_columns.get(column)
                ):
                    continue
                column_type = (
                    str(table_types.get(column, "text"))
                    if isinstance(table_types, dict)
                    else "text"
                )
                if not types_compatible(column_type, column_type):
                    continue
                key = column_key_tokens(table, column, normalized_pass)
                if not is_usable_key(key):
                    continue
                count_key = (table_id, key)
                count = columns_per_table_key.get(count_key, 0) + 1
                columns_per_table_key[count_key] = count
                if count >= max_columns_per_table_key:
                    continue
                columns_by_key.setdefault(key, []).append((table, column))

        key_groups_per_table_signature: dict[str, int] = {}
        accepted: list[tuple[tuple[str, ...], list[tuple[dict[str, Any], str]]]] = []
        for key, columns in columns_by_key.items():
            table_names = list(dict.fromkeys(
                str(table.get("name") or "") for table, _column in columns
            ))
            if len(table_names) < 2:
                continue
            table_signature = ",".join(table_names)
            count = key_groups_per_table_signature.get(table_signature, 0) + 1
            key_groups_per_table_signature[table_signature] = count
            if count <= max_key_groups_per_table_signature:
                accepted.append((key, columns))
        key_groups_by_pass[normalized_pass] = accepted

    profile_cache: dict[tuple[str, str], tuple[bool, bool, int] | None] = {}

    def column_profile(
        table: dict[str, Any], column: str
    ) -> tuple[bool, bool, int] | None:
        cache_key = (str(table["id"]), column)
        if cache_key in profile_cache:
            return profile_cache[cache_key]
        rows = table["rows"]
        column_types = table.get("column_types", {})
        column_type = (
            str(column_types.get(column, "text"))
            if isinstance(column_types, dict)
            else "text"
        )
        values: set[tuple[str, Any]] = set()
        unique = True
        contains_nulls = False
        if not rows:
            profile_cache[cache_key] = None
            return None
        try:
            for row in rows:
                if not isinstance(row, dict):
                    profile_cache[cache_key] = None
                    return None
                key = _relationship_value_key(row.get(column), column_type)
                # Power BI's cardinality probe uses DISTINCTCOUNT plus an
                # ISBLANK scan. DAX model documentation maps empty cells and
                # missing values to BLANK; apply that model-profile rule to a
                # local zero-length text value. Import-path parity remains
                # runtime-unverified.
                if key[0] == "empty":
                    key = ("null", None)
                if key in values:
                    unique = False
                values.add(key)
                if key[0] == "null":
                    contains_nulls = True
        except RelationshipError:
            profile_cache[cache_key] = None
            return None
        result = (unique, contains_nulls, len(values))
        profile_cache[cache_key] = result
        return result

    primary_key_columns: set[tuple[str, str]] = set()
    foreign_key_columns: set[tuple[str, str]] = set()
    tables_by_id = {str(table["id"]): table for table in eligible}
    for from_id, from_column, to_id, to_column, cardinality in existing_relationship_roles:
        if from_id not in tables_by_id or to_id not in tables_by_id:
            continue
        if (
            from_column not in tables_by_id[from_id]["headers"]
            or to_column not in tables_by_id[to_id]["headers"]
        ):
            continue
        if cardinality == "one_to_one":
            from_profile = column_profile(tables_by_id[from_id], from_column)
            to_profile = column_profile(tables_by_id[to_id], to_column)
            if from_profile is None or to_profile is None:
                continue
            if from_profile[2] > to_profile[2]:
                primary_key_columns.add((from_id, from_column))
                foreign_key_columns.add((to_id, to_column))
            else:
                foreign_key_columns.add((from_id, from_column))
                primary_key_columns.add((to_id, to_column))
        else:
            # MapExistingRelationships passes the stored from/to endpoints to
            # AddRelationshipColumnPair for every non-one-to-one relation.
            foreign_key_columns.add((from_id, from_column))
            primary_key_columns.add((to_id, to_column))

    schema_cache: dict[tuple[str, str], bool] = {}
    schema_keys_by_table: dict[str, set[tuple[str, str]]] = {}

    def table_schema_keys(table: dict[str, Any]) -> set[tuple[str, str]]:
        table_id = str(table["id"])
        if table_id in schema_keys_by_table:
            return schema_keys_by_table[table_id]
        columns = [str(column) for column in table["headers"]]
        column_names = {column.casefold() for column in columns}
        calculated_columns = table.get("calculated_columns", [])
        if isinstance(calculated_columns, list):
            for item in calculated_columns:
                name = item.get("name") if isinstance(item, dict) else item
                if isinstance(name, str) and name.casefold() not in column_names:
                    columns.append(name)
                    column_names.add(name.casefold())
        column_types = table.get("column_types", {})
        schema_keys = {
            (
                column,
                str(column_types.get(column, "text"))
                if isinstance(column_types, dict)
                else "text",
            )
            for column in columns
        }
        schema_keys_by_table[table_id] = schema_keys
        return schema_keys

    def has_identical_schema(left: dict[str, Any], right: dict[str, Any]) -> bool:
        pair = tuple(sorted((str(left["id"]), str(right["id"]))))
        if pair in schema_cache:
            return schema_cache[pair]
        left_schema = table_schema_keys(left)
        right_schema = table_schema_keys(right)
        result = len(left_schema) == len(right_schema) and left_schema == right_schema
        schema_cache[pair] = result
        return result

    # Each path node stores (table ID, edge-to-parent-is-direct, all-edges-direct).
    FilterPath = tuple[tuple[str, bool, bool], ...]

    def create_filter_graph(
        graph_relationships: list[dict[str, Any]], forward: bool
    ) -> dict[str, list[tuple[str, bool]]]:
        """Mirror RelationshipGraphEx.CreateRelationshipsFilterGraph."""
        grouped_by_from: dict[str, list[dict[str, Any]]] = {}
        # RelationshipGraphEx stores every model relationship in per-FromTable
        # lists. Its graph builder filters inactive rows only after flattening
        # those lists, so even inactive rows establish the table-group order.
        # The mounted .NET Framework dictionary enumerates its add-only entries
        # by slot index; Python dict order preserves that first-seen grouping.
        for relationship in graph_relationships:
            from_id = relationship.get("from_table_id")
            to_id = relationship.get("to_table_id")
            if not isinstance(from_id, str) or not isinstance(to_id, str):
                continue
            grouped_by_from.setdefault(from_id, []).append(relationship)

        adjacency: dict[str, list[tuple[str, bool]]] = defaultdict(list)
        adjacency_sets: dict[str, set[tuple[str, bool]]] = defaultdict(set)

        def add_edge(source_id: str, target_id: str, is_direct: bool) -> None:
            # FilterGraph<T> stores KeyValuePair<target, isDirect> in a
            # HashSet. Two edges to the same table with different directness
            # remain distinct and can compete during path discovery. .NET's
            # add-only HashSet enumerates by slot index, matching this list.
            edge = (target_id, is_direct)
            if edge not in adjacency_sets[source_id]:
                adjacency_sets[source_id].add(edge)
                adjacency[source_id].append(edge)

        for relationships_for_from in grouped_by_from.values():
            for relationship in relationships_for_from:
                if relationship.get("is_active") is not True:
                    continue
                from_id = str(relationship["from_table_id"])
                to_id = str(relationship["to_table_id"])
                first_id, second_id = (
                    (from_id, to_id) if forward else (to_id, from_id)
                )
                add_edge(first_id, second_id, True)
                if relationship.get("cardinality") == "one_to_one":
                    add_edge(second_id, first_id, True)
                elif relationship.get("cross_filter_direction") == "both":
                    add_edge(second_id, first_id, False)
        return adjacency

    def reachable_table_paths(
        adjacency: dict[str, list[tuple[str, bool]]],
        start_id: str,
    ) -> dict[str, FilterPath]:
        """Keep one DFS path per table, preferring an all-direct path."""
        paths: dict[str, FilterPath] = {start_id: ((start_id, True, True),)}
        # Explicit iterator frames preserve recursive DFS order without Python's
        # recursion-depth limit on large models.
        stack: list[tuple[str, FilterPath, Any]] = [
            (start_id, paths[start_id], iter(adjacency.get(start_id, ())))
        ]
        while stack:
            current_id, current_path, neighbors = stack[-1]
            try:
                next_id, is_direct = next(neighbors)
            except StopIteration:
                stack.pop()
                continue
            all_direct = current_path[-1][2] and is_direct
            proposed_path = (*current_path, (next_id, is_direct, all_direct))
            existing_path = paths.get(next_id)
            if existing_path is not None and (
                existing_path[-1][2] == all_direct or existing_path[-1][2]
            ):
                continue
            paths[next_id] = proposed_path
            stack.append((next_id, proposed_path, iter(adjacency.get(next_id, ()))))
        return paths

    def reverse_path_while_preserving_directness(path: FilterPath) -> FilterPath:
        if not path:
            return path
        reversed_path: FilterPath = ((path[-1][0], True, True),)
        for index in range(len(path) - 2, -1, -1):
            is_direct = path[index + 1][1]
            all_direct = reversed_path[-1][2] and is_direct
            reversed_path = (*reversed_path, (path[index][0], is_direct, all_direct))
        return reversed_path

    def combine_paths(
        path_from_from: FilterPath,
        path_from_candidate_to: FilterPath,
        join_is_direct: bool,
    ) -> FilterPath:
        """Join candidate-To..candidate-From..Y while retaining edge flags."""
        if not path_from_from or not path_from_candidate_to:
            return ()
        joined: FilterPath = path_from_candidate_to
        join_all_direct = joined[-1][2] and join_is_direct
        joined = (*joined, (path_from_from[0][0], join_is_direct, join_all_direct))
        for table_id, is_direct, _all_direct in path_from_from[1:]:
            all_direct = joined[-1][2] and is_direct
            joined = (*joined, (table_id, is_direct, all_direct))
        return joined

    def paths_are_ambiguous(left: FilterPath, right: FilterPath) -> bool:
        if (
            not left
            or not right
            or left[0][0] != right[0][0]
            or left[-1][0] != right[-1][0]
        ):
            return False
        if len(left) == 1 and len(right) == 1:
            return True
        right_ids = {node[0] for node in right}
        left_ids = {node[0] for node in left}
        # PathNode.IsAmbiguous compares the nonshared path segments. Shared
        # tables cancel out; each remaining segment is direct only when all
        # of its own edges are direct.
        left_only = [node for node in left if node[0] not in right_ids]
        right_only = [node for node in right if node[0] not in left_ids]
        left_all_direct = all(node[1] for node in left_only)
        right_all_direct = all(node[1] for node in right_only)
        return left_all_direct == right_all_direct

    def is_path_ambiguous(
        from_id: str,
        to_id: str,
        is_indirect: bool,
        graph_relationships: list[dict[str, Any]],
    ) -> bool:
        forward_adjacency = create_filter_graph(graph_relationships, forward=True)
        reverse_adjacency = create_filter_graph(graph_relationships, forward=False)
        paths_from_to = reachable_table_paths(
            forward_adjacency, to_id
        )
        paths_from_from = reachable_table_paths(
            reverse_adjacency, from_id
        )
        for candidate_to_id, to_path in paths_from_to.items():
            reversed_to_path = reverse_path_while_preserving_directness(to_path)
            paths_from_candidate_to = reachable_table_paths(
                reverse_adjacency, candidate_to_id
            )
            for shared_id in paths_from_from:
                if shared_id not in paths_from_candidate_to:
                    continue
                composed_path = combine_paths(
                    paths_from_from[shared_id],
                    reversed_to_path,
                    join_is_direct=not is_indirect,
                )
                if paths_are_ambiguous(
                    composed_path, paths_from_candidate_to[shared_id]
                ):
                    return True
        return False

    def can_create_relationship(
        candidate: dict[str, Any],
        graph_relationships: list[dict[str, Any]],
    ) -> bool:
        if candidate.get("is_active") is not True:
            return True
        from_id = str(candidate["from_table_id"])
        to_id = str(candidate["to_table_id"])
        cardinality = candidate.get("cardinality")
        behavior = candidate.get("cross_filter_direction")
        if behavior == "single":
            return not is_path_ambiguous(
                from_id, to_id, False, graph_relationships
            )
        if behavior == "both":
            if is_path_ambiguous(from_id, to_id, False, graph_relationships):
                return False
            return not is_path_ambiguous(
                to_id,
                from_id,
                cardinality != "one_to_one",
                graph_relationships,
            )
        return True

    def reverse_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
        reversed_candidate = deepcopy(candidate)
        for left_key, right_key in (
            ("from", "to"),
            ("from_table_id", "to_table_id"),
            ("from_column", "to_column"),
        ):
            reversed_candidate[left_key], reversed_candidate[right_key] = (
                reversed_candidate[right_key],
                reversed_candidate[left_key],
            )
        reversed_candidate["cardinality"] = {
            "many_to_one": "one_to_many",
            "one_to_many": "many_to_one",
        }.get(str(candidate.get("cardinality")), candidate.get("cardinality"))
        return reversed_candidate

    def try_construct_default_relationship(
        candidate: dict[str, Any],
        graph_relationships: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Mirror the helper's active-setting retries and inactive fallback."""
        original = deepcopy(candidate)
        if can_create_relationship(candidate, graph_relationships):
            return candidate

        if candidate.get("cross_filter_direction") == "both":
            if candidate.get("cardinality") != "one_to_one":
                single_candidate = deepcopy(candidate)
                single_candidate["cross_filter_direction"] = "single"
                if can_create_relationship(single_candidate, graph_relationships):
                    return single_candidate
                candidate["is_active"] = False
                return candidate

            many_to_one = deepcopy(candidate)
            many_to_one["cardinality"] = "many_to_one"
            if can_create_relationship(many_to_one, graph_relationships):
                return many_to_one
            one_to_many = reverse_candidate(many_to_one)
            if can_create_relationship(one_to_many, graph_relationships):
                return one_to_many

            many_to_one["cross_filter_direction"] = "single"
            if can_create_relationship(many_to_one, graph_relationships):
                return many_to_one
            one_to_many = reverse_candidate(many_to_one)
            if can_create_relationship(one_to_many, graph_relationships):
                return one_to_many

            original["is_active"] = False
            return original

        if candidate.get("cardinality") == "many_to_one":
            one_to_many = reverse_candidate(candidate)
            if can_create_relationship(one_to_many, graph_relationships):
                return one_to_many
        candidate["is_active"] = False
        return candidate

    # DetectCore emits (candidate column, selected primary-key column) pairs.
    # Keep that shape through the optional path filter; RelationshipEditor
    # builds cardinality, direction, and active state only after filtering.
    pair_candidates: list[
        tuple[dict[str, Any], str, dict[str, Any], str]
    ] = []
    checked_column_pairs: set[tuple[tuple[str, str], tuple[str, str]]] = set()
    for normalized_pass in (False, True):
        for _key, members in key_groups_by_pass[normalized_pass]:
            prioritized_primary_keys: list[
                tuple[int, dict[str, Any], str]
            ] = []
            for table, column in members:
                profile = column_profile(table, column)
                is_explicit_key = table.get("key_column") == column
                if profile is None or (
                    not is_explicit_key and (not profile[0] or profile[1])
                ):
                    continue
                column_key = (str(table["id"]), column)
                # Match the detector's cardinality * 10 + non-FK + PK score.
                # An explicit table key bypasses the uniqueness/null gate;
                # relationship roles come from saved and earlier proposals.
                role_score = (
                    (0 if column_key in foreign_key_columns else 1)
                    + (2 if column_key in primary_key_columns else 0)
                )
                prioritized_primary_keys.append((profile[2] * 10 + role_score, table, column))
            prioritized_primary_keys.sort(key=lambda item: -item[0])

            for _key_cardinality, primary_table, primary_column in prioritized_primary_keys:
                primary_id = str(primary_table["id"])
                for candidate_table, candidate_column in members:
                    candidate_id = str(candidate_table["id"])
                    if primary_id == candidate_id:
                        continue
                    column_pair = tuple(sorted((
                        (primary_id, primary_column),
                        (candidate_id, candidate_column),
                    )))
                    if column_pair in checked_column_pairs:
                        continue
                    checked_column_pairs.add(column_pair)

                    table_pair = tuple(sorted((primary_id, candidate_id)))
                    if table_pair in existing_table_pairs:
                        continue
                    primary_type_map = primary_table.get("column_types", {})
                    candidate_type_map = candidate_table.get("column_types", {})
                    primary_type = (
                        str(primary_type_map.get(primary_column, "text"))
                        if isinstance(primary_type_map, dict)
                        else "text"
                    )
                    candidate_type = (
                        str(candidate_type_map.get(candidate_column, "text"))
                        if isinstance(candidate_type_map, dict)
                        else "text"
                    )
                    if not types_compatible(primary_type, candidate_type):
                        continue
                    candidate_profile = column_profile(candidate_table, candidate_column)
                    if candidate_profile is None:
                        continue
                    primary_profile = column_profile(primary_table, primary_column)
                    if primary_profile is None:
                        continue
                    if has_identical_schema(primary_table, candidate_table):
                        continue

                    candidate_is_one_side = (
                        candidate_profile[0] and not candidate_profile[1]
                    )
                    primary_is_one_side = (
                        primary_profile[0] and not primary_profile[1]
                    )
                    if not primary_is_one_side and not candidate_is_one_side:
                        # CanCreateRelationshipBasic rejects a one-side end
                        # that is neither unique nor null-free.
                        continue
                    pair_candidates.append((
                        candidate_table,
                        candidate_column,
                        primary_table,
                        primary_column,
                    ))
                    # DetectCore adds each proposed pair to its in-memory graph
                    # before it considers later key groups and the second pass.
                    existing_table_pairs.add(table_pair)
                    # AddRelationshipColumnPair receives candidate then primary.
                    foreign_key_columns.add((candidate_id, candidate_column))
                    primary_key_columns.add((primary_id, primary_column))

    selected_pair_candidates = pair_candidates
    if tables_to_be_connected:
        requested_tables = {str(table_id) for table_id in tables_to_be_connected}
        if not requested_tables.issubset(tables_by_id):
            return []

        # FilterAndSortColumnPairs runs on raw detected column pairs before
        # RelationshipEditor constructs cardinality and checks path ambiguity.
        # Defaults for pairs discarded by this scope must not affect admission
        # of the pairs the user asked to connect.
        graph_nodes = set(tables_by_id)
        saved_neighbors: dict[str, list[str]] = defaultdict(list)
        for from_id, to_id in saved_relationship_pairs:
            graph_nodes.update((from_id, to_id))
            saved_neighbors[from_id].append(to_id)
            saved_neighbors[to_id].append(from_id)

        candidate_edges = [
            (str(candidate_table["id"]), str(primary_table["id"]))
            for candidate_table, _candidate_column, primary_table, _primary_column
            in pair_candidates
        ]
        candidate_neighbors: dict[str, list[tuple[int, str]]] = defaultdict(list)
        for index, (from_id, to_id) in enumerate(candidate_edges):
            graph_nodes.update((from_id, to_id))
            candidate_neighbors[from_id].append((index, to_id))
            candidate_neighbors[to_id].append((index, from_id))

        path_length_limit = 1_000_000
        proposal_path_lengths = [path_length_limit] * len(candidate_edges)
        requested_order = [
            str(table["id"]) for table in eligible
            if str(table["id"]) in requested_tables
        ]

        def mark_table_relationships(
            start_id: str, target_ids: set[str]
        ) -> None:
            cache: dict[str, tuple[int, int]] = {}

            def make_frame(
                table_id: str, distance: int
            ) -> tuple[dict[str, Any] | None, int | None]:
                cached = cache.get(table_id)
                if cached is not None and cached[0] <= distance:
                    return None, min(
                        path_length_limit,
                        cached[1] - cached[0] + distance,
                    )
                if table_id not in graph_nodes:
                    return None, path_length_limit
                if table_id in target_ids:
                    cache[table_id] = (distance, distance)
                    return None, distance
                neighbors = [
                    (None, neighbor_id)
                    for neighbor_id in saved_neighbors.get(table_id, ())
                ]
                neighbors.extend(candidate_neighbors.get(table_id, ()))
                cache[table_id] = (distance, path_length_limit)
                return {
                    "table_id": table_id,
                    "distance": distance,
                    "best": path_length_limit,
                    "neighbors": neighbors,
                    "next": 0,
                    "pending_candidate": None,
                }, None

            root, _immediate = make_frame(start_id, 0)
            if root is None:
                return
            stack = [root]
            while stack:
                frame = stack[-1]
                if frame["next"] < len(frame["neighbors"]):
                    candidate_index, neighbor_id = frame["neighbors"][frame["next"]]
                    frame["next"] += 1
                    child, child_result = make_frame(
                        neighbor_id, frame["distance"] + 1
                    )
                    if child is not None:
                        frame["pending_candidate"] = candidate_index
                        stack.append(child)
                        continue
                    frame["best"] = min(frame["best"], int(child_result))
                    cache[frame["table_id"]] = (
                        frame["distance"], frame["best"]
                    )
                    if candidate_index is not None:
                        proposal_path_lengths[candidate_index] = min(
                            proposal_path_lengths[candidate_index], int(child_result)
                        )
                    continue

                result = frame["best"]
                cache[frame["table_id"]] = (frame["distance"], result)
                stack.pop()
                if stack:
                    parent = stack[-1]
                    candidate_index = parent["pending_candidate"]
                    parent["pending_candidate"] = None
                    parent["best"] = min(parent["best"], result)
                    cache[parent["table_id"]] = (
                        parent["distance"], parent["best"]
                    )
                    if candidate_index is not None:
                        proposal_path_lengths[candidate_index] = min(
                            proposal_path_lengths[candidate_index], result
                        )

        for start_id in requested_order:
            mark_table_relationships(
                start_id, requested_tables - {start_id}
            )

        def requested_tables_connected(
            pairs: list[tuple[dict[str, Any], str, dict[str, Any], str]]
        ) -> bool:
            parent = {table_id: table_id for table_id in graph_nodes}

            def find(table_id: str) -> str:
                while parent[table_id] != table_id:
                    parent[table_id] = parent[parent[table_id]]
                    table_id = parent[table_id]
                return table_id

            def join(left_id: str, right_id: str) -> None:
                root_left = find(left_id)
                root_right = find(right_id)
                if root_left != root_right:
                    parent[root_right] = root_left

            for left_id, right_id in saved_relationship_pairs:
                join(left_id, right_id)
            for candidate_table, _candidate_column, primary_table, _primary_column in pairs:
                join(str(candidate_table["id"]), str(primary_table["id"]))
            return len({find(table_id) for table_id in requested_tables}) <= 1

        # The native OrderBy uses only path length. Python's stable sort keeps
        # detector discovery order for equal-length candidate pairs.
        ordered_pairs = sorted(
            enumerate(pair_candidates),
            key=lambda item: proposal_path_lengths[item[0]],
        )
        selected_pair_candidates = []
        for maximum_path_length in range(1, 5):
            filtered_pairs = [
                pair
                for index, pair in ordered_pairs
                if proposal_path_lengths[index] <= maximum_path_length
            ]
            selected_pair_candidates = filtered_pairs
            if requested_tables_connected(filtered_pairs):
                break

    detected: list[dict[str, Any]] = []
    for candidate_table, candidate_column, primary_table, primary_column in selected_pair_candidates:
        candidate_profile = column_profile(candidate_table, candidate_column)
        primary_profile = column_profile(primary_table, primary_column)
        if candidate_profile is None or primary_profile is None:
            continue
        candidate_is_one_side = candidate_profile[0] and not candidate_profile[1]
        primary_is_one_side = primary_profile[0] and not primary_profile[1]
        if not candidate_is_one_side and not primary_is_one_side:
            continue

        # RelationshipEditor passes Pair.Item1 as From and Item2 as To. Its
        # default helper reverses those endpoints when Item2 cannot serve as
        # the unique, null-free one side.
        if primary_is_one_side:
            from_table, from_column = candidate_table, candidate_column
            to_table, to_column = primary_table, primary_column
        else:
            from_table, from_column = primary_table, primary_column
            to_table, to_column = candidate_table, candidate_column
        cardinality = (
            "one_to_one"
            if candidate_is_one_side and primary_is_one_side
            else "many_to_one"
        )
        from_id = str(from_table["id"])
        to_id = str(to_table["id"])
        from_name = str(from_table.get("name", from_id))
        to_name = str(to_table.get("name", to_id))
        proposal = {
            "relationship_version": RELATIONSHIP_VERSION,
            "id": str(uuid4()),
            "from": f"{from_name}[{from_column}]",
            "to": f"{to_name}[{to_column}]",
            "from_table_id": from_id,
            "from_column": from_column,
            "to_table_id": to_id,
            "to_column": to_column,
            "cardinality": cardinality,
            "cross_filter_direction": (
                "both" if cardinality == "one_to_one" else "single"
            ),
            "is_active": True,
        }
        proposal = try_construct_default_relationship(
            proposal, filter_graph_relationships
        )
        if proposal.get("is_active") is True:
            filter_graph_relationships.append(proposal)
        detected.append(proposal)
    return detected
