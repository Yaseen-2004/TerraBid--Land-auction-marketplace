"""Unit tests for WKT validation (no database required)."""

import pytest

from app.core.errors import AppError
from app.core.geo import parse_polygon_wkt

VALID = "POLYGON((77.5946 12.9716, 77.5960 12.9716, 77.5960 12.9728, 77.5946 12.9728, 77.5946 12.9716))"


def test_valid_polygon_is_parsed():
    polygon = parse_polygon_wkt(VALID)
    assert polygon.geom_type == "Polygon"
    assert polygon.is_valid
    assert len(polygon.exterior.coords) == 5


def test_ewkt_with_srid_4326_is_accepted():
    assert parse_polygon_wkt(f"SRID=4326;{VALID}").is_valid


@pytest.mark.parametrize(
    ("wkt", "code", "fragment"),
    [
        ("", "INVALID_WKT", "required"),
        ("POLYGON((77.59 12.97, 77.60 12.97", "INVALID_WKT", "Invalid WKT"),
        ("not a polygon at all", "INVALID_WKT", "Invalid WKT"),
        ("POINT(77.59 12.97)", "INVALID_GEOMETRY_TYPE", "POLYGON"),
        ("LINESTRING(77.59 12.97, 77.60 12.98)", "INVALID_GEOMETRY_TYPE", "POLYGON"),
        ("POLYGON((77.59 12.97, 77.60 12.97, 77.60 12.98, 77.59 12.98))", "INVALID_WKT", "closed"),
        ("POLYGON((0 0, 1 1, 1 0, 0 1, 0 0))", "INVALID_POLYGON", "invalid"),
        ("POLYGON((200 12.97, 201 12.97, 201 12.98, 200 12.98, 200 12.97))", "INVALID_WKT", "out of range"),
        ("POLYGON((12.97 95, 12.98 95, 12.98 96, 12.97 96, 12.97 95))", "INVALID_WKT", "out of range"),
        ("POLYGON((77.59 12.97, 77.60 12.97, 77.59 12.97, 77.59 12.97))", "INVALID_POLYGON", ""),
        ("SRID=3857;" + VALID, "INVALID_WKT", "4326"),
        ("POLYGON((70 10, 80 10, 80 20, 70 20, 70 10))", "INVALID_POLYGON", "too large"),
        ("POLYGON Z((77.5946 12.9716 1, 77.5960 12.9716 1, 77.5960 12.9728 1, 77.5946 12.9716 1))", "INVALID_WKT", "2D"),
    ],
)
def test_invalid_wkt_is_rejected(wkt: str, code: str, fragment: str):
    with pytest.raises(AppError) as exc_info:
        parse_polygon_wkt(wkt)
    assert exc_info.value.error_code == code
    assert exc_info.value.status_code == 422
    assert fragment.lower() in exc_info.value.message.lower()
