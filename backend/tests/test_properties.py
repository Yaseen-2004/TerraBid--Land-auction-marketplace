from datetime import timedelta

from tests.conftest import SAMPLE_WKT, auth_headers, create_user

from app.models import UserRole
from app.services.auction_service import utcnow


def _payload(**overrides):
    now = utcnow()
    payload = {
        "title": "Green Valley Plot",
        "description": "Corner plot",
        "location": "Bengaluru",
        "base_price": 2500000,
        "wkt": SAMPLE_WKT,
        "auction": {
            "start_time": (now + timedelta(minutes=10)).isoformat(),
            "end_time": (now + timedelta(hours=2)).isoformat(),
            "minimum_increment": 50000,
        },
    }
    payload.update(overrides)
    return payload


async def test_create_property_with_auction(client):
    seller = await create_user(UserRole.SELLER)
    response = await client.post("/api/properties", json=_payload(), headers=auth_headers(seller))
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["geometry"]["type"] == "Polygon"
    assert body["wkt"].startswith("POLYGON")
    assert body["area"] > 0  # computed from the polygon via PostGIS geography
    assert body["status"] == "IN_AUCTION"
    assert body["auction"]["status"] == "UPCOMING"
    assert body["auction"]["starting_price"] == 2500000
    assert body["auction"]["min_next_bid"] == 2500000
    lat, lon = body["centroid"]
    assert 12.97 < lat < 12.98 and 77.59 < lon < 77.60


async def test_invalid_wkt_is_rejected_with_clear_error(client):
    seller = await create_user(UserRole.SELLER)
    response = await client.post(
        "/api/properties",
        json=_payload(wkt="POLYGON((77.59 12.97, 77.60 12.97, 77.60 12.98, 77.59 12.98))"),
        headers=auth_headers(seller),
    )
    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["error_code"] == "INVALID_WKT"
    assert "closed" in body["message"]


async def test_invalid_price_and_dates(client):
    seller = await create_user(UserRole.SELLER)
    headers = auth_headers(seller)
    assert (await client.post("/api/properties", json=_payload(base_price=-5), headers=headers)).status_code == 422

    now = utcnow()
    bad_window = _payload(
        auction={
            "start_time": (now + timedelta(hours=2)).isoformat(),
            "end_time": (now + timedelta(hours=1)).isoformat(),
            "minimum_increment": 1000,
        }
    )
    response = await client.post("/api/properties", json=bad_window, headers=headers)
    assert response.status_code == 422
    assert "after the start time" in response.json()["message"]

    naive = _payload(auction={"start_time": "2030-01-01T10:00:00", "end_time": "2030-01-01T12:00:00", "minimum_increment": 1})
    assert (await client.post("/api/properties", json=naive, headers=headers)).status_code == 422


async def test_bidder_cannot_create_property(client):
    bidder = await create_user(UserRole.BIDDER)
    response = await client.post("/api/properties", json=_payload(), headers=auth_headers(bidder))
    assert response.status_code == 403


async def test_property_retrieval_and_spatial_filter(client):
    seller = await create_user(UserRole.SELLER)
    created = (await client.post("/api/properties", json=_payload(), headers=auth_headers(seller))).json()

    fetched = await client.get(f"/api/properties/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "Green Valley Plot"

    inside = await client.get("/api/properties", params={"bbox": "77.5,12.9,77.7,13.0"})
    outside = await client.get("/api/properties", params={"bbox": "72.0,18.0,73.0,19.0"})
    assert [p["id"] for p in inside.json()] == [created["id"]]
    assert outside.json() == []

    assert (await client.get("/api/properties/99999")).json()["error_code"] == "PROPERTY_NOT_FOUND"


async def test_only_owner_or_admin_can_modify(client):
    owner = await create_user(UserRole.SELLER)
    other = await create_user(UserRole.SELLER)
    admin = await create_user(UserRole.ADMIN)
    created = (await client.post("/api/properties", json=_payload(auction=None), headers=auth_headers(owner))).json()

    forbidden = await client.put(f"/api/properties/{created['id']}", json={"title": "Hijacked"}, headers=auth_headers(other))
    assert forbidden.status_code == 403

    updated = await client.put(f"/api/properties/{created['id']}", json={"title": "Renamed Plot"}, headers=auth_headers(admin))
    assert updated.status_code == 200
    assert updated.json()["title"] == "Renamed Plot"

    deleted = await client.delete(f"/api/properties/{created['id']}", headers=auth_headers(owner))
    assert deleted.status_code == 204
    assert (await client.get(f"/api/properties/{created['id']}")).status_code == 404
