from datetime import timedelta
from decimal import Decimal

from tests.conftest import auth_headers, create_auction, create_user

from app.models import AuctionStatus, PropertyStatus, UserRole
from app.services import auction_service
from app.services.redis_service import redis_service


async def test_admin_starts_upcoming_auction(client):
    seller = await create_user(UserRole.SELLER)
    admin = await create_user(UserRole.ADMIN)
    auction = await create_auction(seller, status=AuctionStatus.UPCOMING, starts_in=timedelta(hours=1))

    response = await client.put(f"/api/auctions/{auction.id}/start", headers=auth_headers(admin))
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "LIVE"
    state = await redis_service.get_state(auction.id)
    assert state["auction_status"] == "LIVE"


async def test_non_admin_cannot_manage_lifecycle(client):
    seller = await create_user(UserRole.SELLER)
    auction = await create_auction(seller)
    for action in ("start", "end", "cancel"):
        response = await client.put(f"/api/auctions/{auction.id}/{action}", headers=auth_headers(seller))
        assert response.status_code == 403


async def test_end_auction_determines_winner(client, db):
    seller = await create_user(UserRole.SELLER)
    admin = await create_user(UserRole.ADMIN)
    alice, bob = await create_user(name="Alice"), await create_user(name="Bob")
    auction = await create_auction(seller)

    await auction_service.place_bid(db, alice, auction.id, Decimal("1000000"))
    await auction_service.place_bid(db, bob, auction.id, Decimal("1100000"))

    response = await client.put(f"/api/auctions/{auction.id}/end", headers=auth_headers(admin))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ENDED"
    assert body["winner_id"] == bob.id
    assert body["winner_name"] == "Bob"
    assert body["current_price"] == 1100000

    prop = (await client.get(f"/api/properties/{body['property_id']}")).json()
    assert prop["status"] == PropertyStatus.SOLD.value

    again = await client.put(f"/api/auctions/{auction.id}/end", headers=auth_headers(admin))
    assert again.status_code == 409


async def test_invalid_auction(client):
    admin = await create_user(UserRole.ADMIN)
    assert (await client.get("/api/auctions/424242")).json()["error_code"] == "AUCTION_NOT_FOUND"
    response = await client.put("/api/auctions/424242/start", headers=auth_headers(admin))
    assert response.status_code == 404


async def test_expired_auction_is_finalised_by_lifecycle(db):
    seller = await create_user(UserRole.SELLER)
    auction = await create_auction(seller, starts_in=timedelta(hours=-2), duration=timedelta(hours=1))

    await auction_service.finalize_auction(db, auction.id)
    refreshed = await auction_service.get_auction(db, auction.id)
    assert refreshed.status == AuctionStatus.ENDED
    assert refreshed.winner_id is None
    assert refreshed.property.status == PropertyStatus.UNSOLD


async def test_lifecycle_promotes_due_auction(db):
    seller = await create_user(UserRole.SELLER)
    auction = await create_auction(seller, status=AuctionStatus.UPCOMING, starts_in=timedelta(seconds=-1))
    await auction_service.start_auction(db, auction.id)
    assert (await auction_service.get_auction(db, auction.id)).status == AuctionStatus.LIVE


async def test_cancel_auction_rejects_further_bids(client, db):
    seller = await create_user(UserRole.SELLER)
    admin = await create_user(UserRole.ADMIN)
    bidder = await create_user()
    auction = await create_auction(seller)

    assert (await client.put(f"/api/auctions/{auction.id}/cancel", headers=auth_headers(admin))).status_code == 200
    response = await client.post(f"/api/auctions/{auction.id}/bid", json={"amount": 1000000}, headers=auth_headers(bidder))
    assert response.status_code == 409
    assert response.json()["error_code"] == "AUCTION_CANCELLED"


async def test_redis_state_is_rehydrated_after_loss(client, db):
    seller = await create_user(UserRole.SELLER)
    alice, bob = await create_user(), await create_user()
    auction = await create_auction(seller)
    await auction_service.place_bid(db, alice, auction.id, Decimal("1000000"))

    await redis_service.client.flushdb()  # simulate a Redis restart without persistence

    too_low = await client.post(f"/api/auctions/{auction.id}/bid", json={"amount": 1005000}, headers=auth_headers(bob))
    assert too_low.status_code == 422
    assert too_low.json()["details"]["current_price"] == 1000000

    ok = await client.post(f"/api/auctions/{auction.id}/bid", json={"amount": 1010000}, headers=auth_headers(bob))
    assert ok.status_code == 200, ok.text
    assert ok.json()["auction"]["bid_count"] == 2
