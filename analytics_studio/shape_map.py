"""Read bounded local GeoJSON and TopoJSON region boundaries for Shape maps."""

from __future__ import annotations

from functools import lru_cache
import json
import math
from pathlib import Path
from typing import Any


MAX_BOUNDARY_FILE_BYTES = 8 * 1024 * 1024
MAX_BOUNDARY_FEATURES = 5_000
MAX_BOUNDARY_VERTICES = 100_000


class ShapeMapError(ValueError):
    """A boundary source is unsupported or exceeds the local import limits."""


def available_topology_objects(path: str | Path) -> list[str]:
    """Return selectable geometry object names from a TopoJSON file."""
    document = _read_document(Path(path))
    objects = document.get("objects")
    if document.get("type") != "Topology" or not isinstance(objects, dict):
        return []
    return [str(name) for name, item in objects.items() if isinstance(item, dict)]


def boundary_key_properties(features: list[dict[str, Any]]) -> list[str]:
    """Return feature properties populated on the majority of the shapes."""
    if not features:
        return []
    counts: dict[str, int] = {}
    for feature in features:
        for name, value in feature.get("properties", {}).items():
            if value is not None and str(value).strip():
                counts[str(name)] = counts.get(str(name), 0) + 1
    minimum = max(1, math.ceil(len(features) * 0.8))
    keys = [name for name, count in counts.items() if count >= minimum]
    preferred = {"name": 0, "name_1": 1, "admin": 2, "id": 3, "iso_a3": 4, "code": 5}
    return sorted(keys, key=lambda name: (preferred.get(name.casefold(), 10), name.casefold(), name))


def load_boundary_features(
    path: str | Path,
    *,
    object_name: str = "",
) -> list[dict[str, Any]]:
    """Load Polygon and MultiPolygon features into a compact local shape form."""
    resolved = Path(path).expanduser().resolve()
    try:
        stat = resolved.stat()
    except OSError as exc:
        raise ShapeMapError("Choose a readable GeoJSON or TopoJSON boundary file.") from exc
    if not resolved.is_file():
        raise ShapeMapError("Choose a readable GeoJSON or TopoJSON boundary file.")
    if stat.st_size > MAX_BOUNDARY_FILE_BYTES:
        raise ShapeMapError("Boundary files must be 8 MB or smaller.")
    return _load_boundary_features_cached(
        str(resolved), stat.st_mtime_ns, stat.st_size, str(object_name)
    )


def _read_document(path: Path) -> dict[str, Any]:
    try:
        if not path.is_file() or path.stat().st_size > MAX_BOUNDARY_FILE_BYTES:
            raise ShapeMapError("Boundary files must be readable and 8 MB or smaller.")
        document = json.loads(path.read_text(encoding="utf-8"))
    except ShapeMapError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ShapeMapError("The boundary file must contain valid UTF-8 GeoJSON or TopoJSON.") from exc
    if not isinstance(document, dict):
        raise ShapeMapError("The boundary file must contain a GeoJSON or TopoJSON object.")
    return document


@lru_cache(maxsize=8)
def _load_boundary_features_cached(
    file_path: str,
    modified_ns: int,
    file_size: int,
    object_name: str,
) -> list[dict[str, Any]]:
    del modified_ns, file_size
    path = Path(file_path)
    document = _read_document(path)
    if document.get("type") == "Topology":
        return _topology_features(document, object_name)
    return _geojson_features(document)


def _geojson_features(document: dict[str, Any]) -> list[dict[str, Any]]:
    kind = document.get("type")
    if kind == "FeatureCollection":
        source_features = document.get("features")
    elif kind == "Feature":
        source_features = [document]
    elif kind in {"Polygon", "MultiPolygon"}:
        source_features = [{"type": "Feature", "geometry": document, "properties": {}}]
    else:
        source_features = None
    if not isinstance(source_features, list):
        raise ShapeMapError("GeoJSON must be a FeatureCollection of Polygon or MultiPolygon regions.")

    vertices = [0]
    features: list[dict[str, Any]] = []
    for index, source in enumerate(source_features):
        if not isinstance(source, dict):
            continue
        geometry = source.get("geometry", source)
        polygons = _geojson_polygons(geometry, vertices)
        if not polygons:
            continue
        properties = _properties(source.get("properties"))
        feature_id = source.get("id")
        if feature_id is not None and "id" not in properties:
            properties["id"] = _property_text(feature_id)
        features.append({"id": _property_text(feature_id) or str(index), "properties": properties, "polygons": polygons})
        _check_feature_count(len(features))
    return _require_features(features)


def _geojson_polygons(geometry: Any, vertices: list[int]) -> list[list[list[list[float]]]]:
    if not isinstance(geometry, dict):
        return []
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if kind == "Polygon":
        source_polygons = [coordinates]
    elif kind == "MultiPolygon":
        source_polygons = coordinates
    else:
        return []
    if not isinstance(source_polygons, list):
        return []
    result: list[list[list[list[float]]]] = []
    for source_polygon in source_polygons:
        if not isinstance(source_polygon, list):
            continue
        rings: list[list[list[float]]] = []
        for source_ring in source_polygon:
            if not isinstance(source_ring, list):
                continue
            ring = [_position(value, vertices) for value in source_ring]
            ring = [position for position in ring if position is not None]
            if len(ring) >= 3:
                rings.append(ring)
        if rings:
            result.append(rings)
    return result


def _topology_features(document: dict[str, Any], object_name: str) -> list[dict[str, Any]]:
    objects = document.get("objects")
    arcs = document.get("arcs")
    if not isinstance(objects, dict) or not isinstance(arcs, list):
        raise ShapeMapError("TopoJSON needs an objects collection and an arcs array.")
    object_names = [str(name) for name, item in objects.items() if isinstance(item, dict)]
    selected_name = object_name or (object_names[0] if len(object_names) == 1 else "")
    topology_object = objects.get(selected_name) if selected_name else None
    if not isinstance(topology_object, dict):
        raise ShapeMapError("Choose one geometry object from the TopoJSON file.")

    transform = document.get("transform")
    scale = transform.get("scale") if isinstance(transform, dict) else None
    translate = transform.get("translate") if isinstance(transform, dict) else None
    if transform is not None:
        if (
            not isinstance(scale, list) or len(scale) < 2
            or not isinstance(translate, list) or len(translate) < 2
        ):
            raise ShapeMapError("TopoJSON transform needs two scale and translate values.")
        try:
            scale = [float(scale[0]), float(scale[1])]
            translate = [float(translate[0]), float(translate[1])]
        except (TypeError, ValueError) as exc:
            raise ShapeMapError("TopoJSON transform values must be finite numbers.") from exc
        if not all(math.isfinite(value) for value in (*scale, *translate)):
            raise ShapeMapError("TopoJSON transform values must be finite numbers.")
    arc_cache: dict[int, list[list[float]]] = {}
    vertices = [0]
    expanded_vertices = [0]

    def decode_arc(reference: Any) -> list[list[float]]:
        if isinstance(reference, bool) or not isinstance(reference, int):
            raise ShapeMapError("TopoJSON contains an invalid arc reference.")
        reverse = reference < 0
        arc_index = ~reference if reverse else reference
        if not 0 <= arc_index < len(arcs):
            raise ShapeMapError("TopoJSON contains an arc reference outside the arcs array.")
        if arc_index not in arc_cache:
            source_arc = arcs[arc_index]
            if not isinstance(source_arc, list):
                raise ShapeMapError("TopoJSON arcs must be coordinate arrays.")
            decoded: list[list[float]] = []
            x = y = 0.0
            for delta in source_arc:
                if not isinstance(delta, list) or len(delta) < 2:
                    continue
                try:
                    dx, dy = float(delta[0]), float(delta[1])
                except (TypeError, ValueError):
                    continue
                if scale is not None and translate is not None:
                    x += dx
                    y += dy
                    position = [x * float(scale[0]) + float(translate[0]), y * float(scale[1]) + float(translate[1])]
                else:
                    position = [dx, dy]
                if all(math.isfinite(value) for value in position):
                    decoded.append(position)
                    _count_vertex(vertices)
            arc_cache[arc_index] = decoded
        points = arc_cache[arc_index]
        return list(reversed(points)) if reverse else points

    def decode_ring(reference_list: Any) -> list[list[float]]:
        if not isinstance(reference_list, list):
            return []
        points: list[list[float]] = []
        for reference in reference_list:
            arc_points = decode_arc(reference)
            for _ in arc_points[1:] if points and arc_points else arc_points:
                _count_vertex(expanded_vertices)
            points.extend(arc_points[1:] if points and arc_points else arc_points)
        return points

    def decode_geometry(source: Any, index: int) -> None:
        if not isinstance(source, dict):
            return
        kind = source.get("type")
        coordinates = source.get("arcs")
        if kind == "GeometryCollection":
            geometries = source.get("geometries")
            if isinstance(geometries, list):
                for child_index, child in enumerate(geometries):
                    decode_geometry(child, child_index)
            return
        if kind == "Polygon":
            source_polygons = [coordinates]
        elif kind == "MultiPolygon":
            source_polygons = coordinates
        else:
            return
        if not isinstance(source_polygons, list):
            return
        polygons: list[list[list[list[float]]]] = []
        for source_polygon in source_polygons:
            if not isinstance(source_polygon, list):
                continue
            rings = [ring for ring in (decode_ring(refs) for refs in source_polygon) if len(ring) >= 3]
            if rings:
                polygons.append(rings)
        if polygons:
            properties = _properties(source.get("properties"))
            feature_id = source.get("id")
            if feature_id is not None and "id" not in properties:
                properties["id"] = _property_text(feature_id)
            features.append({"id": _property_text(feature_id) or str(index), "properties": properties, "polygons": polygons})
            _check_feature_count(len(features))

    features: list[dict[str, Any]] = []
    if topology_object.get("type") == "GeometryCollection":
        source_geometries = topology_object.get("geometries")
        if isinstance(source_geometries, list):
            for index, geometry in enumerate(source_geometries):
                decode_geometry(geometry, index)
    else:
        decode_geometry(topology_object, 0)
    return _require_features(features)


def _properties(value: Any) -> dict[str, str | int | float | bool | None]:
    if not isinstance(value, dict):
        return {}
    return {
        str(name): text
        for name, item in value.items()
        if (text := _property_value(item)) is not _UNSUPPORTED
    }


_UNSUPPORTED = object()


def _property_value(value: Any) -> str | int | float | bool | None | object:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    return _UNSUPPORTED


def _property_text(value: Any) -> str:
    if value is None or isinstance(value, (dict, list)):
        return ""
    return str(value).strip()


def _position(value: Any, vertices: list[int]) -> list[float] | None:
    if not isinstance(value, list) or len(value) < 2:
        return None
    try:
        x, y = float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x) or not math.isfinite(y):
        return None
    _count_vertex(vertices)
    return [x, y]


def _count_vertex(vertices: list[int]) -> None:
    vertices[0] += 1
    if vertices[0] > MAX_BOUNDARY_VERTICES:
        raise ShapeMapError("Boundary files can contain at most 100,000 coordinate points.")


def _check_feature_count(count: int) -> None:
    if count > MAX_BOUNDARY_FEATURES:
        raise ShapeMapError("Boundary files can contain at most 5,000 regions.")


def _require_features(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not features:
        raise ShapeMapError("The boundary file has no Polygon or MultiPolygon regions.")
    return features
