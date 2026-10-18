"""Server-side WKT polygon validation. Nothing reaches PostGIS unless it passes these checks."""

import math
import re

from shapely import wkt as shapely_wkt
from shapely.errors import ShapelyError
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient
from shapely.validation import explain_validity

from app.core.errors import AppError

MAX_WKT_LENGTH = 100_000
MAX_VERTICES = 2_000
MAX_SPAN_DEGREES = 5.0
SRID = 4326

_EWKT_PREFIX = re.compile(r"^\s*SRID\s*=\s*(\d+)\s*;\s*", re.IGNORECASE)


def _invalid(message: str, code: str = "INVALID_WKT") -> AppError:
    return AppError(message, code, 422, details=[{"field": "wkt", "message": message}])


def parse_polygon_wkt(raw: str) -> Polygon:
    """Parse and validate a WKT POLYGON in EPSG:4326 (longitude latitude order)."""
    if not isinstance(raw, str) or not raw.strip():
        raise _invalid("A WKT polygon is required.")
    text = raw.strip()
    if len(text) > MAX_WKT_LENGTH:
        raise _invalid(f"WKT is too long (maximum {MAX_WKT_LENGTH} characters).")

    srid_match = _EWKT_PREFIX.match(text)
    if srid_match:
        if int(srid_match.group(1)) != SRID:
            raise _invalid("Only SRID 4326 (WGS 84 longitude/latitude) coordinates are supported.")
        text = text[srid_match.end():]

    try:
        geometry = shapely_wkt.loads(text)
    except (ShapelyError, ValueError, TypeError) as exc:
        if "closed" in str(exc).lower():
            raise _invalid("Polygon ring must be closed: the first and last coordinates must be identical.") from exc
        raise _invalid(
            "Invalid WKT syntax. Expected a format like POLYGON((lon lat, lon lat, lon lat, lon lat))."
        ) from exc

    if geometry.geom_type != "Polygon":
        raise _invalid(f"Geometry must be a POLYGON, received {geometry.geom_type.upper()}.", "INVALID_GEOMETRY_TYPE")
    if geometry.is_empty:
        raise _invalid("Polygon must not be empty.", "INVALID_POLYGON")
    if geometry.has_z:
        raise _invalid("Only 2D coordinates (longitude latitude) are supported.")

    rings = [geometry.exterior, *geometry.interiors]
    vertex_count = sum(len(ring.coords) for ring in rings)
    if vertex_count > MAX_VERTICES:
        raise _invalid(f"Polygon has too many vertices (maximum {MAX_VERTICES}).", "INVALID_POLYGON")

    for ring in rings:
        for x, y in ring.coords:
            if not (math.isfinite(x) and math.isfinite(y)):
                raise _invalid("Coordinates must be finite numbers.")
            if not (-180 <= x <= 180 and -90 <= y <= 90):
                hint = " Coordinates may be swapped: WKT uses 'longitude latitude' order." if abs(x) <= 90 < abs(y) <= 180 else ""
                raise _invalid(f"Coordinate ({x} {y}) is out of range for longitude/latitude.{hint}")

    if len(set(geometry.exterior.coords)) < 3:
        raise _invalid("Polygon needs at least three distinct vertices.", "INVALID_POLYGON")
    if not geometry.is_valid:
        raise _invalid(f"Polygon geometry is invalid: {explain_validity(geometry)}.", "INVALID_POLYGON")
    if geometry.area <= 0:
        raise _invalid("Polygon has zero area.", "INVALID_POLYGON")

    min_x, min_y, max_x, max_y = geometry.bounds
    if (max_x - min_x) > MAX_SPAN_DEGREES or (max_y - min_y) > MAX_SPAN_DEGREES:
        raise _invalid(f"Polygon is too large (maximum span {MAX_SPAN_DEGREES} degrees).", "INVALID_POLYGON")

    return orient(geometry, sign=1.0)
