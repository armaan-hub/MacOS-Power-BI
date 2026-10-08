"""Validation helpers for local model relationship metadata."""

from __future__ import annotations

from collections import defaultdict, deque
from copy import deepcopy
from decimal import Decimal, DecimalException
from typing import Any


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
    if relationship.get("cardinality") == "many_to_one":
        return ("to_from",)
    return ("from_to",)


def propagate_relationship_filters(
    tables: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    filter_table_ids: set[str],
) -> dict[str, list[dict[str, Any]]]:
    """Propagate explicitly filtered rows across active, loaded relationships."""
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

    edges_by_source: dict[str, list[tuple[str, str, str, str, str]]] = defaultdict(list)

    def add_edge(
        source_id: str,
        source_column: str,
        target_id: str,
        target_column: str,
    ) -> None:
        source_table = tables_by_id[source_id]
        target_table = tables_by_id[target_id]
        if source_column not in source_table["headers"] or target_column not in target_table["headers"]:
            raise RelationshipError("An active relationship refers to a column that is no longer loaded.")
        source_type = str(source_table.get("column_types", {}).get(source_column, "text"))
        target_type = str(target_table.get("column_types", {}).get(target_column, "text"))
        compatible = source_type == target_type or {source_type, target_type} <= {
            "whole_number", "decimal_number",
        }
        if not compatible:
            raise RelationshipError("An active relationship has incompatible column types.")
        edges_by_source[source_id].append(
            (target_id, source_column, target_column, source_type, target_type)
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
        if "from_to" in filter_directions:
            add_edge(from_id, from_column, to_id, to_column)
        if "to_from" in filter_directions:
            add_edge(to_id, to_column, from_id, from_column)

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
    while constrained:
        source_id = constrained.popleft()
        for target_id, source_column, target_column, source_type, target_type in edges_by_source.get(source_id, []):
            source_keys = {
                _relationship_value_key(row.get(source_column), source_type)
                for row in rows_by_id[source_id]
            }
            current_target_rows = rows_by_id[target_id]
            filtered_target_rows = [
                row for row in current_target_rows
                if _relationship_value_key(row.get(target_column), target_type) in source_keys
            ]
            changed = len(filtered_target_rows) != len(current_target_rows)
            if changed:
                rows_by_id[target_id] = filtered_target_rows
            if target_id not in constrained_ids or changed:
                constrained_ids.add(target_id)
                constrained.append(target_id)

    return rows_by_id


def _relationship_value_key(value: Any, column_type: str) -> tuple[str, Any]:
    if value is None or str(value) == "":
        return "blank", ""
    text = str(value)
    if column_type in {"whole_number", "decimal_number"}:
        try:
            number = Decimal(text)
        except DecimalException as exc:
            raise RelationshipError("A relationship key contains a value that is not numeric.") from exc
        if not number.is_finite() or (
            column_type == "whole_number" and number != number.to_integral_value()
        ):
            raise RelationshipError("A relationship key contains a value that does not match its model type.")
        return "number", number
    return "value", text


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
