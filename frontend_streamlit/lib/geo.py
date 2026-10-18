"""Client-side geometry helpers. The server (app/core/geo.py) is still the
authoritative validator — this is only for the live preview map and for
matching a map click back to a property polygon.
"""

from __future__ import annotations

from shapely.geometry import Point, shape
from shapely.errors import ShapelyError
from shapely import wkt as shapely_wkt


def parse_wkt_preview(text: str) -> list[tuple[float, float]] | None:
    """Returns exterior ring coordinates as (lat, lon) pairs for folium, or None if unparsable."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        geometry = shapely_wkt.loads(text.split(";", 1)[-1] if text.upper().startswith("SRID=") else text)
    except (ShapelyError, ValueError):
        return None
    if geometry.geom_type != "Polygon" or geometry.is_empty:
        return None
    return [(lat, lon) for lon, lat in geometry.exterior.coords]


def find_property_at(lat: float, lon: float, properties: list[dict]) -> dict | None:
    """Point-in-polygon match for a map click, used since folium/st_folium doesn't return
    which vector layer was clicked directly (see app.py for why)."""
    point = Point(lon, lat)
    for prop in properties:
        geometry = prop.get("geometry")
        if not geometry:
            continue
        try:
            polygon = shape(geometry)
        except (ShapelyError, ValueError, TypeError):
            continue
        if polygon.buffer(0.00005).contains(point):  # small tolerance for imprecise clicks
            return prop
    return None
