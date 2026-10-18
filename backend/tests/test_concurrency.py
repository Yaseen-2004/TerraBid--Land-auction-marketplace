"""Concurrency tests: many simultaneous bids against real Redis + PostgreSQL.

Invariants verified:
* only bids that satisfy the rules at the moment they are evaluated are accepted
* accepted bids form a strictly increasing chain respecting the minimum increment
* exactly one highest bid / winner exists and it is identical in Redis and PostgreSQL
* the number of accepted bids agrees across API results, Redis and PostgreSQL
"""

import asyncio
import random
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from tests.conftest import auth_headers, create_auction, create_user, create_users

from app.core.errors import AppError
from app.database import SessionLocal
from app.models import Bid, BidStatus, UserRole
from app.services import auction_service
from app.services.redis_service import BID_STREAM_KEY, redis_service

pytestmark = pytest.mark.usefixtures("clean")

STARTING = Decimal("1000000")
INCREMENT = Decimal("10000")


async def _bid(user, auction_id: int, amount: Decimal, idempotency_key: str | None = None):
    async with SessionLocal() as session:
        try:
            result = await auction_service.place_bid(
                session, user, auction_id, amount, idempotency_key=idempotency_key
            )
            return ("ACCEPTED", result)
        except AppError as exc:
            return (exc.error_code, exc)


async def _accepted_bids(auction_id: int) -> list[Bid]:
    async with SessionLocal() as session:
        return list(
            (
                await session.scalars(
                    select(Bid)
                    .where(Bid.auction_id == auction_id, Bid.status == BidStatus.ACCEPTED)
                    .order_by(Bid.sequence)
                )
            ).all()
        )


def _assert_valid_chain(bids: list[Bid]) -> None:
    assert [b.sequence for b in bids] == list(range(1, len(bids) + 1)), "sequences must be gap-free and unique"
    assert bids[0].amount >= STARTING
    for previous, current in zip(bids, bids[1:]):
        assert current.amount >= previous.amount + INCREMENT, "every accepted bid must beat the previous one"
        assert current.bidder_id != previous.bidder_id


async def test_thousand_concurrent_random_bids_stay_consistent():
    seller = await create_user(UserRole.SELLER)
    auction = await create_auction(seller, starting_price=STARTING, increment=INCREMENT)
    bidders = await create_users(200)

    rng = random.Random(42)
    attempts = [
        (bidders[i % len(bidders)], STARTING + INCREMENT * rng.randint(0, 3000))
        for i in range(1000)
    ]
    outcomes = await asyncio.gather(*(_bid(user, auction.id, amount) for user, amount in attempts))

    accepted_results = [r for code, r in outcomes if code == "ACCEPTED"]
    rejected_codes = {code for code, _ in outcomes if code != "ACCEPTED"}
    assert accepted_results, "at least one bid must win"
    assert rejected_codes <= {"BID_TOO_LOW", "OUTBID", "ALREADY_HIGHEST_BIDDER"}

    ledger = await _accepted_bids(auction.id)
    assert len(ledger) == len(accepted_results)
    _assert_valid_chain(ledger)

    state = await redis_service.get_state(auction.id)
    top = ledger[-1]
    assert int(state["bid_count"]) == len(ledger)
    assert auction_service.from_minor(state["highest_bid"]) == top.amount
    assert int(state["highest_bidder"]) == top.bidder_id
    assert top.amount == max(r.bid.amount for r in accepted_results)
    assert await redis_service.client.xlen(BID_STREAM_KEY) == 0

    async with SessionLocal() as session:
        await auction_service.finalize_auction(session, auction.id, force=True)
    async with SessionLocal() as session:
        final = await auction_service.get_auction(session, auction.id)
        assert final.winner_id == top.bidder_id
        assert final.current_price == top.amount


async def test_identical_simultaneous_bids_have_exactly_one_winner():
    seller = await create_user(UserRole.SELLER)
    auction = await create_auction(seller, starting_price=STARTING, increment=INCREMENT)
    bidders = await create_users(500)

    outcomes = await asyncio.gather(*(_bid(user, auction.id, STARTING) for user in bidders))

    accepted = [r for code, r in outcomes if code == "ACCEPTED"]
    assert len(accepted) == 1, f"expected a single winner, got {len(accepted)}"
    assert sum(1 for code, _ in outcomes if code == "BID_TOO_LOW") == 499
    ledger = await _accepted_bids(auction.id)
    assert len(ledger) == 1 and ledger[0].bidder_id == accepted[0].bid.bidder_id


async def test_duplicate_concurrent_requests_are_applied_once():
    seller = await create_user(UserRole.SELLER)
    bidder = await create_user()
    auction = await create_auction(seller, starting_price=STARTING, increment=INCREMENT)
    key = str(uuid.uuid4())

    outcomes = await asyncio.gather(*(_bid(bidder, auction.id, STARTING, idempotency_key=key) for _ in range(100)))

    assert all(code == "ACCEPTED" for code, _ in outcomes)
    assert sum(1 for _, r in outcomes if not r.duplicate) == 1
    assert len({r.bid.id for _, r in outcomes}) == 1
    assert len(await _accepted_bids(auction.id)) == 1


async def test_concurrent_http_bids(client):
    seller = await create_user(UserRole.SELLER)
    auction = await create_auction(seller, starting_price=STARTING, increment=INCREMENT)
    bidders = await create_users(300)

    async def post(user, amount):
        return await client.post(
            f"/api/auctions/{auction.id}/bid",
            json={"amount": str(amount)},
            headers={**auth_headers(user), "Idempotency-Key": uuid.uuid4().hex},
        )

    rng = random.Random(7)
    responses = await asyncio.gather(
        *(post(user, STARTING + INCREMENT * rng.randint(0, 500)) for user in bidders)
    )
    statuses = {r.status_code for r in responses}
    assert statuses <= {200, 409, 422}, statuses
    accepted = [r.json() for r in responses if r.status_code == 200]

    ledger = await _accepted_bids(auction.id)
    assert len(ledger) == len(accepted)
    _assert_valid_chain(ledger)
    final = (await client.get(f"/api/auctions/{auction.id}")).json()
    assert Decimal(str(final["current_price"])) == ledger[-1].amount
    assert final["highest_bidder_id"] == ledger[-1].bidder_id


async def test_bids_racing_auction_close_never_slip_through():
    seller = await create_user(UserRole.SELLER)
    auction = await create_auction(seller, starting_price=STARTING, increment=INCREMENT)
    bidders = await create_users(400)

    async def close_soon():
        await asyncio.sleep(0.02)
        async with SessionLocal() as session:
            await auction_service.finalize_auction(session, auction.id, force=True)

    amounts = [STARTING + INCREMENT * i for i in range(len(bidders))]
    random.Random(3).shuffle(amounts)
    results = await asyncio.gather(
        close_soon(), *(_bid(user, auction.id, amount) for user, amount in zip(bidders, amounts))
    )
    outcomes = results[1:]

    async with SessionLocal() as session:
        final = await auction_service.get_auction(session, auction.id)
    ledger = await _accepted_bids(auction.id)
    accepted = [r for code, r in outcomes if code == "ACCEPTED"]

    assert len(ledger) == len(accepted), "every accepted bid is persisted"
    state = await redis_service.get_state(auction.id)
    assert state["auction_status"] == "ENDED"
    assert int(state["bid_count"]) == len(ledger), "no bid was accepted by Redis without reaching the ledger"

    straggler_code, _ = await _bid(bidders[0], auction.id, STARTING + INCREMENT * 10_000)
    assert straggler_code == "AUCTION_ENDED"
    if ledger:
        _assert_valid_chain(ledger)
        assert final.winner_id == ledger[-1].bidder_id
        assert final.current_price == ledger[-1].amount
    else:
        assert final.winner_id is None
    late = {code for code, _ in outcomes if code not in ("ACCEPTED", "BID_TOO_LOW", "OUTBID", "ALREADY_HIGHEST_BIDDER")}
    assert late <= {"AUCTION_ENDED"}
