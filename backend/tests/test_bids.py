import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from tests.conftest import auth_headers, create_auction, create_user

from app.models import AuctionStatus, Bid, BidStatus, UserRole
from app.services import auction_service
from app.services.redis_service import BID_STREAM_KEY, redis_service


async def test_valid_bid_is_accepted_persisted_and_published(client, db):
    seller = await create_user(UserRole.SELLER)
    bidder = await create_user(name="User123")
    auction = await create_auction(seller)

    pubsub = redis_service.client.pubsub(ignore_subscribe_messages=True)
    await pubsub.subscribe(f"auction_events:{auction.id}")

    response = await client.post(
        f"/api/auctions/{auction.id}/bid", json={"amount": 1000000}, headers=auth_headers(bidder)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["auction"]["current_price"] == 1000000
    assert body["auction"]["min_next_bid"] == 1010000
    assert body["auction"]["highest_bidder"] == "User123"

    bids = (await db.scalars(select(Bid).where(Bid.auction_id == auction.id))).all()
    assert len(bids) == 1 and bids[0].status == BidStatus.ACCEPTED
    assert await redis_service.client.xlen(BID_STREAM_KEY) == 0  # persisted and removed from the stream

    message = None
    for _ in range(20):  # the first read may only consume the subscribe confirmation
        message = await pubsub.get_message(timeout=0.2)
        if message is not None:
            break
    await pubsub.aclose()
    assert message is not None and '"BID_ACCEPTED"' in message["data"]

    history = await client.get(f"/api/auctions/{auction.id}/bids")
    assert [b["bidder_name"] for b in history.json()] == ["User123"]


async def test_bid_below_minimum_increment(client):
    seller = await create_user(UserRole.SELLER)
    alice, bob = await create_user(), await create_user()
    auction = await create_auction(seller)

    first_too_low = await client.post(f"/api/auctions/{auction.id}/bid", json={"amount": 999999}, headers=auth_headers(alice))
    assert first_too_low.status_code == 422
    assert first_too_low.json()["error_code"] == "BID_TOO_LOW"

    assert (await client.post(f"/api/auctions/{auction.id}/bid", json={"amount": 1000000}, headers=auth_headers(alice))).status_code == 200
    response = await client.post(f"/api/auctions/{auction.id}/bid", json={"amount": 1009999}, headers=auth_headers(bob))
    assert response.status_code == 422
    body = response.json()
    assert body == {
        "success": False,
        "message": "Bid is below the minimum increment.",
        "error_code": "BID_TOO_LOW",
        "details": {"current_price": 1000000.0, "min_next_bid": 1010000.0, "highest_bidder": alice.name, "duplicate": False},
    }


async def test_outbid_message_when_client_saw_stale_price(client):
    seller = await create_user(UserRole.SELLER)
    alice, bob = await create_user(), await create_user()
    auction = await create_auction(seller)
    await client.post(f"/api/auctions/{auction.id}/bid", json={"amount": 1000000}, headers=auth_headers(alice))

    response = await client.post(
        f"/api/auctions/{auction.id}/bid",
        json={"amount": 1000000, "expected_current_price": 0},
        headers=auth_headers(bob),
    )
    assert response.status_code == 409
    assert response.json()["message"] == "Bid rejected because a higher bid was received."


async def test_bidding_rules(client):
    seller = await create_user(UserRole.SELLER)
    admin = await create_user(UserRole.ADMIN)
    bidder = await create_user()
    auction = await create_auction(seller)
    url = f"/api/auctions/{auction.id}/bid"

    own = await client.post(url, json={"amount": 1000000}, headers=auth_headers(seller))
    assert own.status_code == 403 and own.json()["message"] == "Unauthorized bidder."

    assert (await client.post(url, json={"amount": 1000000}, headers=auth_headers(admin))).status_code == 403

    for bad in ({"amount": -5}, {"amount": 0}, {"amount": "abc"}, {"amount": 10.123}, {}):
        response = await client.post(url, json=bad, headers=auth_headers(bidder))
        assert response.status_code == 422, bad

    assert (await client.post(url, json={"amount": 1000000}, headers=auth_headers(bidder))).status_code == 200
    again = await client.post(url, json={"amount": 1100000}, headers=auth_headers(bidder))
    assert again.json()["error_code"] == "ALREADY_HIGHEST_BIDDER"

    missing = await client.post("/api/auctions/987654/bid", json={"amount": 1000000}, headers=auth_headers(bidder))
    assert missing.status_code == 404
    assert missing.json()["message"] == "Auction does not exist."


async def test_bidding_after_auction_ends(client, db):
    seller = await create_user(UserRole.SELLER)
    bidder = await create_user()

    expired = await create_auction(seller, starts_in=timedelta(hours=-2), duration=timedelta(hours=1))
    response = await client.post(f"/api/auctions/{expired.id}/bid", json={"amount": 1000000}, headers=auth_headers(bidder))
    assert response.status_code == 409
    assert response.json()["message"] == "Auction has ended."

    upcoming = await create_auction(seller, status=AuctionStatus.UPCOMING, starts_in=timedelta(hours=1))
    response = await client.post(f"/api/auctions/{upcoming.id}/bid", json={"amount": 1000000}, headers=auth_headers(bidder))
    assert response.json()["error_code"] == "AUCTION_NOT_LIVE"

    rejected = (await db.scalars(select(Bid).where(Bid.status == BidStatus.REJECTED))).all()
    assert {b.rejection_reason for b in rejected} == {"AUCTION_ENDED", "AUCTION_NOT_LIVE"}


async def test_duplicate_request_with_idempotency_key(client, db):
    seller = await create_user(UserRole.SELLER)
    bidder = await create_user()
    auction = await create_auction(seller)
    headers = {**auth_headers(bidder), "Idempotency-Key": str(uuid.uuid4())}

    first = await client.post(f"/api/auctions/{auction.id}/bid", json={"amount": 1000000}, headers=headers)
    second = await client.post(f"/api/auctions/{auction.id}/bid", json={"amount": 1000000}, headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True
    assert first.json()["bid"]["id"] == second.json()["bid"]["id"]
    assert len((await db.scalars(select(Bid).where(Bid.auction_id == auction.id))).all()) == 1


async def test_failed_persistence_is_reconciled_from_stream(db):
    seller = await create_user(UserRole.SELLER)
    bidder = await create_user()
    auction = await create_auction(seller)

    # Simulate PostgreSQL being unavailable at acceptance time.
    original = auction_service.persist_accepted_bids

    async def failing(*args, **kwargs):
        raise DBAPIError("INSERT", {}, Exception("database down"))

    auction_service.persist_accepted_bids = failing
    try:
        result = await auction_service.place_bid(db, bidder, auction.id, Decimal("1000000"))
    finally:
        auction_service.persist_accepted_bids = original

    assert result.success
    assert await redis_service.client.xlen(BID_STREAM_KEY) == 1
    assert (await db.scalars(select(Bid))).all() == []

    await auction_service.reconcile_stream(db)
    bids = (await db.scalars(select(Bid))).all()
    assert len(bids) == 1 and bids[0].id == result.bid.id
    assert await redis_service.client.xlen(BID_STREAM_KEY) == 0


async def test_bid_ledger_is_immutable(db):
    seller = await create_user(UserRole.SELLER)
    bidder = await create_user()
    auction = await create_auction(seller)
    await auction_service.place_bid(db, bidder, auction.id, Decimal("1000000"))

    try:
        await db.execute(text("UPDATE bids SET amount = 1"))
        await db.commit()
        raise AssertionError("bid update should have been rejected")
    except DBAPIError as exc:
        await db.rollback()
        assert "immutable" in str(exc)
