"""Auction domain logic.

Consistency model
-----------------
* Redis is authoritative for *live* bidding state. bid.lua validates and applies a
  bid atomically and, in the same atomic step, appends the accepted bid to the
  `bids:stream` persistence stream.
* PostgreSQL is authoritative for everything permanent. After a bid is accepted
  the API persists it immediately (idempotently, keyed by the bid UUID) and removes
  the stream entry. If that write fails, the entry stays in the stream and the
  lifecycle worker's reconciler persists it later.
* When an auction closes, Redis is closed first (so no further bids can be
  accepted), the stream is drained for that auction, and only then is the winner
  computed from PostgreSQL and committed.
* If Redis loses state (restart without persistence), state is re-hydrated from
  PostgreSQL on first use. Hydration never overwrites existing Redis state.

Lock ordering (prevents deadlocks): auction row lock first, then bid inserts.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from redis.exceptions import RedisError
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import AppError
from app.models import Auction, AuctionStatus, Bid, BidStatus, Property, PropertyStatus, User, UserRole
from app.schemas.auction import AuctionCreate, AuctionOut, AuctionSchedule, AuctionUpdate, PropertyBrief
from app.schemas.bid import BidOut, BidPlacementResponse, LiveAuctionState
from app.services.permissions import ensure_can_manage_property
from app.services.redis_service import redis_service

logger = logging.getLogger(__name__)

MONEY_QUANTUM = Decimal("0.01")
ACTIVE_STATUSES = (AuctionStatus.UPCOMING, AuctionStatus.LIVE)
TERMINAL_STATUSES = (AuctionStatus.ENDED, AuctionStatus.CANCELLED)
MIN_AUCTION_DURATION = timedelta(minutes=1)
MAX_AUCTION_DURATION = timedelta(days=90)
START_TIME_GRACE = timedelta(minutes=5)
STREAM_PAGE_SIZE = 500

REJECTIONS: dict[str, tuple[int, str]] = {
    "AUCTION_ENDED": (409, "Auction has ended."),
    "AUCTION_CANCELLED": (409, "Auction has been cancelled."),
    "AUCTION_NOT_LIVE": (409, "Auction is not live yet."),
    "BID_TOO_LOW": (422, "Bid is below the minimum increment."),
    "OUTBID": (409, "Bid rejected because a higher bid was received."),
    "ALREADY_HIGHEST_BIDDER": (409, "You are already the highest bidder."),
    "UNAUTHORIZED_BIDDER": (403, "Unauthorized bidder."),
    "INVALID_AMOUNT": (422, "Bid amount must be a positive whole number of paise."),
}


# ---------------------------------------------------------------------------- helpers


def utcnow() -> datetime:
    return datetime.now(UTC)


def to_minor(value: Decimal) -> int:
    return int((Decimal(value) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def from_minor(value: int | str) -> Decimal:
    return (Decimal(int(value)) / 100).quantize(MONEY_QUANTUM)


def to_ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def from_ms(value: int | str) -> datetime:
    return datetime.fromtimestamp(int(value) / 1000, tz=UTC)


def iso_now() -> str:
    return utcnow().isoformat().replace("+00:00", "Z")


def make_event(name: str, auction_id: int, **payload: Any) -> dict[str, Any]:
    return {"event": name, "event_id": uuid.uuid4().hex, "auction_id": auction_id, "timestamp": iso_now(), **payload}


async def publish_safely(auction_id: int, event: dict[str, Any]) -> None:
    try:
        await redis_service.publish_event(auction_id, event)
    except RedisError:
        logger.exception("Failed to publish %s for auction %s", event.get("event"), auction_id)


@dataclass(slots=True)
class AcceptedBid:
    bid_id: uuid.UUID
    auction_id: int
    bidder_id: int
    amount: Decimal
    bid_time: datetime
    sequence: int
    idempotency_key: str | None

    @classmethod
    def from_stream(cls, fields: dict[str, str]) -> AcceptedBid:
        return cls(
            bid_id=uuid.UUID(fields["bid_id"]),
            auction_id=int(fields["auction_id"]),
            bidder_id=int(fields["bidder_id"]),
            amount=from_minor(fields["amount"]),
            bid_time=from_ms(fields["bid_time_ms"]),
            sequence=int(fields["version"]),
            idempotency_key=fields.get("idem") or None,
        )


def validate_schedule(start: datetime, end: datetime, *, allow_past_start: bool = False) -> None:
    now = utcnow()
    if end <= start:
        raise AppError("Auction end time must be after the start time.", "INVALID_AUCTION_WINDOW", 422)
    if end - start < MIN_AUCTION_DURATION:
        raise AppError("Auction must run for at least 1 minute.", "INVALID_AUCTION_WINDOW", 422)
    if end - start > MAX_AUCTION_DURATION:
        raise AppError("Auction cannot run for longer than 90 days.", "INVALID_AUCTION_WINDOW", 422)
    if end <= now:
        raise AppError("Auction end time must be in the future.", "INVALID_AUCTION_WINDOW", 422)
    if not allow_past_start and start < now - START_TIME_GRACE:
        raise AppError("Auction start time cannot be in the past.", "INVALID_AUCTION_WINDOW", 422)


# ---------------------------------------------------------------------------- reads & serialisation


async def _live_states(auction_ids: list[int]) -> dict[int, dict[str, str]]:
    try:
        states = await redis_service.get_states(auction_ids)
    except RedisError:
        logger.warning("Redis unavailable while reading live state; falling back to PostgreSQL")
        return {}
    return {aid: state for aid, state in states.items() if "auction_status" in state}


async def _bid_counts(db: AsyncSession, auction_ids: list[int]) -> dict[int, int]:
    if not auction_ids:
        return {}
    rows = await db.execute(
        select(Bid.auction_id, func.count())
        .where(Bid.auction_id.in_(auction_ids), Bid.status == BidStatus.ACCEPTED)
        .group_by(Bid.auction_id)
    )
    return {aid: count for aid, count in rows.all()}


async def _top_bids(db: AsyncSession, auction_ids: list[int]) -> dict[int, tuple[int, str, Decimal]]:
    if not auction_ids:
        return {}
    rows = await db.execute(
        select(Bid.auction_id, Bid.bidder_id, User.name, Bid.amount)
        .join(User, User.id == Bid.bidder_id)
        .where(Bid.auction_id.in_(auction_ids), Bid.status == BidStatus.ACCEPTED)
        .order_by(Bid.auction_id, Bid.amount.desc(), Bid.bid_time.asc())
        .distinct(Bid.auction_id)
    )
    return {aid: (bidder_id, name, amount) for aid, bidder_id, name, amount in rows.all()}


async def build_auction_views(
    db: AsyncSession, auctions: list[Auction], *, include_property: bool = True
) -> list[AuctionOut]:
    if not auctions:
        return []
    ids = [a.id for a in auctions]
    live = await _live_states([a.id for a in auctions if a.status in ACTIVE_STATUSES])
    counts = await _bid_counts(db, ids)
    tops = await _top_bids(db, ids)

    views: list[AuctionOut] = []
    for auction in auctions:
        state = live.get(auction.id)
        winner_name = tops[auction.id][1] if auction.winner_id and auction.id in tops else None
        if state:
            bid_count = int(state.get("bid_count") or 0)
            starting = from_minor(state["starting_price"])
            increment = from_minor(state["min_increment"])
            current = from_minor(state["highest_bid"]) if bid_count else starting
            highest_id = int(state["highest_bidder"]) if bid_count and state.get("highest_bidder") else None
            highest_name = (state.get("highest_bidder_name") or None) if bid_count else None
        else:
            bid_count = counts.get(auction.id, 0)
            starting = auction.starting_price
            increment = auction.minimum_increment
            top = tops.get(auction.id)
            current = max(auction.current_price, top[2]) if top else auction.starting_price
            highest_id = top[0] if top else None
            highest_name = top[1] if top else None

        views.append(
            AuctionOut(
                id=auction.id,
                property_id=auction.property_id,
                status=auction.status,
                starting_price=starting,
                current_price=current,
                minimum_increment=increment,
                min_next_bid=current + increment if bid_count else starting,
                start_time=auction.start_time,
                end_time=auction.end_time,
                bid_count=bid_count,
                highest_bidder_id=highest_id,
                highest_bidder=highest_name,
                winner_id=auction.winner_id,
                winner_name=winner_name,
                created_at=auction.created_at,
                updated_at=auction.updated_at,
                property=PropertyBrief(
                    id=auction.property.id,
                    title=auction.property.title,
                    location=auction.property.location,
                    status=auction.property.status,
                    created_by=auction.property.created_by,
                )
                if include_property
                else None,
            )
        )
    return views


async def get_auction(db: AsyncSession, auction_id: int, *, lock: bool = False) -> Auction:
    stmt = select(Auction).where(Auction.id == auction_id).execution_options(populate_existing=True)
    if lock:
        stmt = stmt.with_for_update(of=Auction)
    auction = await db.scalar(stmt)
    if auction is None:
        raise AppError("Auction does not exist.", "AUCTION_NOT_FOUND", 404)
    return auction


async def get_auction_view(db: AsyncSession, auction_id: int) -> AuctionOut:
    auction = await get_auction(db, auction_id)
    return (await build_auction_views(db, [auction]))[0]


async def list_auctions(
    db: AsyncSession,
    *,
    statuses: list[AuctionStatus] | None,
    property_id: int | None,
    limit: int,
    offset: int,
) -> list[AuctionOut]:
    stmt = select(Auction)
    if statuses:
        stmt = stmt.where(Auction.status.in_(statuses))
    if property_id is not None:
        stmt = stmt.where(Auction.property_id == property_id)
    stmt = stmt.order_by(Auction.start_time.desc()).limit(limit).offset(offset)
    auctions = list((await db.scalars(stmt)).unique().all())
    return await build_auction_views(db, auctions)


async def list_bids(
    db: AsyncSession, auction_id: int, *, include_rejected: bool, limit: int, offset: int
) -> list[BidOut]:
    stmt = (
        select(Bid, User.name)
        .join(User, User.id == Bid.bidder_id)
        .where(Bid.auction_id == auction_id)
        .order_by(Bid.bid_time.desc(), Bid.amount.desc())
        .limit(limit)
        .offset(offset)
    )
    if not include_rejected:
        stmt = stmt.where(Bid.status == BidStatus.ACCEPTED)
    rows = await db.execute(stmt)
    return [
        BidOut(
            id=bid.id,
            auction_id=bid.auction_id,
            bidder_id=bid.bidder_id,
            bidder_name=name,
            amount=bid.amount,
            bid_time=bid.bid_time,
            status=bid.status,
            rejection_reason=bid.rejection_reason,
        )
        for bid, name in rows.all()
    ]


async def get_snapshot(db: AsyncSession, auction_id: int) -> dict[str, Any]:
    """Full state sent to WebSocket clients on connect and on explicit resync."""
    auction = await get_auction(db, auction_id)
    view = (await build_auction_views(db, [auction]))[0]
    bids = await list_bids(db, auction_id, include_rejected=False, limit=25, offset=0)
    state = (await _live_states([auction_id])).get(auction_id, {})
    return make_event(
        "SNAPSHOT",
        auction_id,
        auction=view.model_dump(mode="json"),
        bids=[b.model_dump(mode="json") for b in bids],
        epoch=int(state.get("epoch", 0)),
        seq=int(state.get("version", 0)),
    )


# ---------------------------------------------------------------------------- Redis hydration


async def ensure_loaded(db: AsyncSession, auction_id: int) -> Auction:
    """Load auction state into Redis from PostgreSQL if it is missing (e.g. after a Redis restart)."""
    auction = await get_auction(db, auction_id)
    top = (
        await db.execute(
            select(Bid.bidder_id, User.name, Bid.amount, Bid.bid_time)
            .join(User, User.id == Bid.bidder_id)
            .where(Bid.auction_id == auction_id, Bid.status == BidStatus.ACCEPTED)
            .order_by(Bid.amount.desc(), Bid.bid_time.asc())
            .limit(1)
        )
    ).first()
    bid_count, max_sequence = (
        await db.execute(
            select(func.count(), func.coalesce(func.max(Bid.sequence), 0)).where(
                Bid.auction_id == auction_id, Bid.status == BidStatus.ACCEPTED
            )
        )
    ).one()

    mapping = {
        "auction_id": str(auction.id),
        "auction_status": auction.status.value,
        "start_ms": str(to_ms(auction.start_time)),
        "end_ms": str(to_ms(auction.end_time)),
        "starting_price": str(to_minor(auction.starting_price)),
        "min_increment": str(to_minor(auction.minimum_increment)),
        "highest_bid": str(to_minor(top.amount)) if top else "0",
        "highest_bidder": str(top.bidder_id) if top else "",
        "highest_bidder_name": top.name if top else "",
        "last_bid_time": str(to_ms(top.bid_time)) if top else "0",
        "bid_count": str(bid_count),
        "version": str(max_sequence),
        # A new epoch lets clients order events correctly across Redis restarts.
        "epoch": str(to_ms(utcnow())),
        "seller_id": str(auction.property.created_by),
    }
    ttl = settings.ended_state_ttl_seconds if auction.status in TERMINAL_STATUSES else 0
    if await redis_service.hydrate(auction.id, mapping, ttl):
        logger.info("Hydrated Redis state for auction %s (status=%s)", auction.id, auction.status.value)
    return auction


async def _redis_transition(
    db: AsyncSession, auction_id: int, status: AuctionStatus, *, start_ms: int | None = None, end_ms: int | None = None
) -> dict[str, Any]:
    result = await redis_service.transition(auction_id, status.value, start_ms=start_ms, end_ms=end_ms)
    if result["code"] == "NOT_LOADED":
        await ensure_loaded(db, auction_id)
        result = await redis_service.transition(auction_id, status.value, start_ms=start_ms, end_ms=end_ms)
    return result


# ---------------------------------------------------------------------------- persistence


async def persist_accepted_bids(db: AsyncSession, bids: list[AcceptedBid]) -> None:
    """Idempotently write accepted bids. Caller commits.

    The auction row is locked (UPDATE) before bid rows are inserted, matching the
    lock order used by finalisation, so concurrent writers cannot deadlock.
    """
    if not bids:
        return
    highest: dict[int, Decimal] = {}
    for bid in bids:
        highest[bid.auction_id] = max(highest.get(bid.auction_id, bid.amount), bid.amount)
    for auction_id in sorted(highest):
        await db.execute(
            update(Auction)
            .where(Auction.id == auction_id)
            .values(current_price=func.greatest(Auction.current_price, highest[auction_id]))
            .execution_options(synchronize_session=False)
        )
    await db.execute(
        pg_insert(Bid)
        .values(
            [
                {
                    "id": bid.bid_id,
                    "auction_id": bid.auction_id,
                    "bidder_id": bid.bidder_id,
                    "amount": bid.amount,
                    "bid_time": bid.bid_time,
                    "status": BidStatus.ACCEPTED,
                    "sequence": bid.sequence,
                    "idempotency_key": bid.idempotency_key,
                }
                for bid in bids
            ]
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )


async def _persist_rejected_bid(
    db: AsyncSession, *, bid_id: uuid.UUID, auction_id: int, bidder_id: int, amount: Decimal, reason: str,
    bid_time: datetime, idempotency_key: str | None,
) -> None:
    try:
        await db.execute(
            pg_insert(Bid)
            .values(
                id=bid_id,
                auction_id=auction_id,
                bidder_id=bidder_id,
                amount=amount,
                bid_time=bid_time,
                status=BidStatus.REJECTED,
                rejection_reason=reason,
                idempotency_key=idempotency_key,
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        logger.warning("Could not record rejected bid %s for auction %s", bid_id, auction_id, exc_info=True)


async def reconcile_stream(
    db: AsyncSession, *, auction_id: int | None = None, min_age_ms: int | None = None, commit: bool = True
) -> list[str]:
    """Persist accepted bids still waiting in the Redis stream.

    With commit=True entries are committed per auction and deleted from the stream;
    otherwise the caller must commit and then delete the returned entry ids.
    """
    cutoff = to_ms(utcnow()) - min_age_ms if min_age_ms is not None else None
    collected: list[tuple[str, AcceptedBid]] = []
    malformed: list[str] = []
    start = "-"
    while True:
        entries = await redis_service.read_bid_stream(start=start, count=STREAM_PAGE_SIZE)
        reached_cutoff = False
        for entry_id, fields in entries:
            if cutoff is not None and int(entry_id.split("-", 1)[0]) > cutoff:
                reached_cutoff = True
                break
            if auction_id is not None and fields.get("auction_id") != str(auction_id):
                continue
            try:
                collected.append((entry_id, AcceptedBid.from_stream(fields)))
            except (KeyError, ValueError):
                logger.error("Dropping malformed bid stream entry %s: %s", entry_id, fields)
                malformed.append(entry_id)
        if reached_cutoff or len(entries) < STREAM_PAGE_SIZE:
            break
        start = f"({entries[-1][0]}"

    if malformed:
        await redis_service.delete_stream_entries(malformed)
    if not collected:
        return []

    if not commit:
        await persist_accepted_bids(db, [bid for _, bid in collected])
        return [entry_id for entry_id, _ in collected]

    by_auction: dict[int, list[tuple[str, AcceptedBid]]] = defaultdict(list)
    for entry_id, bid in collected:
        by_auction[bid.auction_id].append((entry_id, bid))
    for aid, items in sorted(by_auction.items()):
        try:
            await persist_accepted_bids(db, [bid for _, bid in items])
            await db.commit()
        except SQLAlchemyError:
            await db.rollback()
            logger.exception("Reconciliation of %s bids for auction %s failed; will retry", len(items), aid)
            continue
        await redis_service.delete_stream_entries([entry_id for entry_id, _ in items])
        logger.info("Reconciled %s accepted bids for auction %s from the Redis stream", len(items), aid)
    return []


# ---------------------------------------------------------------------------- scheduling


async def schedule_auction(db: AsyncSession, prop: Property, schedule: AuctionSchedule) -> Auction:
    if prop.status in (PropertyStatus.SOLD, PropertyStatus.WITHDRAWN):
        raise AppError("This property can no longer be auctioned.", "PROPERTY_NOT_AUCTIONABLE", 409)
    active = await db.scalar(
        select(Auction.id).where(Auction.property_id == prop.id, Auction.status.in_(ACTIVE_STATUSES)).limit(1)
    )
    if active is not None:
        raise AppError("This property already has an upcoming or live auction.", "AUCTION_ALREADY_ACTIVE", 409)
    validate_schedule(schedule.start_time, schedule.end_time)

    starting_price = schedule.starting_price or prop.base_price
    auction = Auction(
        property_id=prop.id,
        starting_price=starting_price,
        current_price=starting_price,
        minimum_increment=schedule.minimum_increment,
        start_time=schedule.start_time,
        end_time=schedule.end_time,
        status=AuctionStatus.UPCOMING,
    )
    db.add(auction)
    prop.status = PropertyStatus.IN_AUCTION
    try:
        await db.flush()
    except IntegrityError as exc:
        raise AppError("This property already has an upcoming or live auction.", "AUCTION_ALREADY_ACTIVE", 409) from exc
    return auction


async def create_auction(db: AsyncSession, user: User, data: AuctionCreate) -> AuctionOut:
    prop = await db.get(Property, data.property_id)
    if prop is None:
        raise AppError("Property does not exist.", "PROPERTY_NOT_FOUND", 404)
    ensure_can_manage_property(user, prop)
    auction = await schedule_auction(db, prop, data)
    await db.commit()
    return await get_auction_view(db, auction.id)


async def update_auction(db: AsyncSession, user: User, auction_id: int, data: AuctionUpdate) -> AuctionOut:
    auction = await get_auction(db, auction_id, lock=True)
    ensure_can_manage_property(user, auction.property)
    if auction.status != AuctionStatus.UPCOMING:
        raise AppError("Only upcoming auctions can be modified.", "AUCTION_NOT_EDITABLE", 409)

    changes = data.model_dump(exclude_unset=True, exclude_none=True)
    start = changes.get("start_time", auction.start_time)
    end = changes.get("end_time", auction.end_time)
    validate_schedule(start, end)
    auction.start_time = start
    auction.end_time = end
    if "minimum_increment" in changes:
        auction.minimum_increment = changes["minimum_increment"]
    if "starting_price" in changes:
        auction.starting_price = changes["starting_price"]
        auction.current_price = changes["starting_price"]
    await db.commit()

    # Upcoming auctions cannot hold bids, so dropping cached state is safe; it is re-hydrated on demand.
    try:
        await redis_service.delete_auction_state(auction_id)
    except RedisError:
        logger.warning("Could not clear cached Redis state for auction %s", auction_id)
    return await get_auction_view(db, auction_id)


# ---------------------------------------------------------------------------- lifecycle transitions


async def start_auction(db: AsyncSession, auction_id: int, *, manual: bool = False) -> Auction:
    auction = await get_auction(db, auction_id, lock=True)
    now = utcnow()
    if auction.status != AuctionStatus.UPCOMING:
        await db.rollback()
        if manual:
            raise AppError("Only upcoming auctions can be started.", "AUCTION_NOT_UPCOMING", 409)
        return auction
    if auction.end_time <= now:
        await db.rollback()
        if manual:
            raise AppError("The auction end time has already passed.", "AUCTION_EXPIRED", 409)
        return auction
    if auction.start_time > now:
        if not manual:
            await db.rollback()
            return auction
        auction.start_time = now

    auction.status = AuctionStatus.LIVE
    auction.property.status = PropertyStatus.IN_AUCTION
    await db.commit()
    # updated_at uses a server-side onupdate default, so SQLAlchemy expires it after
    # commit; refresh before touching it again to avoid a lazy load outside greenlet context.
    await db.refresh(auction)
    await db.refresh(auction.property)

    epoch = seq = 0
    try:
        result = await _redis_transition(db, auction.id, AuctionStatus.LIVE, start_ms=to_ms(auction.start_time))
        state = result.get("state", {})
        epoch, seq = int(state.get("epoch", 0)), int(state.get("version", 0))
    except RedisError:
        logger.exception("Auction %s is LIVE in PostgreSQL but Redis sync failed; repair loop will retry", auction.id)

    view = (await build_auction_views(db, [auction]))[0]
    await publish_safely(
        auction.id,
        make_event("AUCTION_STARTED", auction.id, auction=view.model_dump(mode="json"), epoch=epoch, seq=seq),
    )
    logger.info("Auction %s is now LIVE", auction.id)
    return auction


async def finalize_auction(db: AsyncSession, auction_id: int, *, manual: bool = False, force: bool = False) -> Auction:
    auction = await get_auction(db, auction_id, lock=True)
    now = utcnow()
    if auction.status in TERMINAL_STATUSES:
        await db.rollback()
        if manual:
            raise AppError("Auction has already been closed.", "AUCTION_ALREADY_CLOSED", 409)
        return auction
    if manual and auction.status != AuctionStatus.LIVE:
        await db.rollback()
        raise AppError("Only live auctions can be ended. Cancel upcoming auctions instead.", "AUCTION_NOT_LIVE", 409)
    if not manual and not force and auction.end_time > now:
        await db.rollback()
        return auction

    effective_end = min(auction.end_time, now)

    # 1. Close in Redis first: from this instant bid.lua rejects every new bid.
    result = await _redis_transition(db, auction.id, AuctionStatus.ENDED, end_ms=to_ms(effective_end))
    if result["code"] == "TERMINAL" and result.get("auction_status") == AuctionStatus.CANCELLED.value:
        await db.rollback()
        return await cancel_auction(db, auction_id)
    state = result.get("state", {})

    # 2. Drain accepted bids that have not reached PostgreSQL yet.
    stream_ids = await reconcile_stream(db, auction_id=auction.id, commit=False)

    # 3. Winner = highest accepted bid in the permanent ledger.
    top = (
        await db.execute(
            select(Bid.bidder_id, Bid.amount)
            .where(Bid.auction_id == auction.id, Bid.status == BidStatus.ACCEPTED)
            .order_by(Bid.amount.desc(), Bid.bid_time.asc())
            .limit(1)
        )
    ).first()
    if state and int(state.get("bid_count") or 0) > 0:
        redis_top = (int(state["highest_bidder"]), from_minor(state["highest_bid"]))
        if top is None or (top.bidder_id, top.amount) != redis_top:
            logger.error("Winner mismatch for auction %s: postgres=%s redis=%s", auction.id, top, redis_top)

    auction.status = AuctionStatus.ENDED
    auction.end_time = effective_end
    if top is not None:
        auction.winner_id = top.bidder_id
        auction.current_price = top.amount
        auction.property.status = PropertyStatus.SOLD
    else:
        auction.property.status = PropertyStatus.UNSOLD
    await db.commit()
    await db.refresh(auction)
    await db.refresh(auction.property)

    try:
        await redis_service.delete_stream_entries(stream_ids)
        await redis_service.expire_auction(auction.id, settings.ended_state_ttl_seconds)
    except RedisError:
        logger.warning("Post-finalisation Redis cleanup failed for auction %s", auction.id)

    view = (await build_auction_views(db, [auction]))[0]
    await publish_safely(
        auction.id,
        make_event(
            "AUCTION_ENDED",
            auction.id,
            auction=view.model_dump(mode="json"),
            winner_id=view.winner_id,
            winner_name=view.winner_name,
            final_price=float(view.current_price) if view.bid_count else None,
            epoch=int(state.get("epoch", 0)),
            seq=int(state.get("version", 0)),
        ),
    )
    logger.info("Auction %s ENDED (winner=%s, price=%s)", auction.id, view.winner_id, view.current_price)
    return auction


async def cancel_auction(db: AsyncSession, auction_id: int) -> Auction:
    auction = await get_auction(db, auction_id, lock=True)
    if auction.status in TERMINAL_STATUSES:
        await db.rollback()
        raise AppError("Auction has already been closed.", "AUCTION_ALREADY_CLOSED", 409)

    result = await _redis_transition(db, auction.id, AuctionStatus.CANCELLED)
    if result["code"] == "TERMINAL":
        await db.rollback()
        raise AppError("Auction has already been closed.", "AUCTION_ALREADY_CLOSED", 409)
    state = result.get("state", {})

    stream_ids = await reconcile_stream(db, auction_id=auction.id, commit=False)
    auction.status = AuctionStatus.CANCELLED
    if auction.property.status != PropertyStatus.SOLD:
        auction.property.status = PropertyStatus.AVAILABLE
    await db.commit()
    await db.refresh(auction)
    await db.refresh(auction.property)

    try:
        await redis_service.delete_stream_entries(stream_ids)
        await redis_service.expire_auction(auction.id, settings.ended_state_ttl_seconds)
    except RedisError:
        logger.warning("Post-cancellation Redis cleanup failed for auction %s", auction.id)

    view = (await build_auction_views(db, [auction]))[0]
    await publish_safely(
        auction.id,
        make_event(
            "AUCTION_CANCELLED",
            auction.id,
            auction=view.model_dump(mode="json"),
            epoch=int(state.get("epoch", 0)),
            seq=int(state.get("version", 0)),
        ),
    )
    logger.info("Auction %s CANCELLED", auction.id)
    return auction


async def repair_live_state(db: AsyncSession, auction_id: int) -> None:
    """Bring Redis in line with a LIVE auction in PostgreSQL (after Redis restarts or partial failures)."""
    state = await redis_service.get_state(auction_id)
    if not state or "auction_status" not in state:
        await ensure_loaded(db, auction_id)
        return
    redis_status = state["auction_status"]
    if redis_status == AuctionStatus.LIVE.value:
        return
    if redis_status == AuctionStatus.UPCOMING.value:
        auction = await get_auction(db, auction_id)
        await _redis_transition(db, auction_id, AuctionStatus.LIVE, start_ms=to_ms(auction.start_time))
        await db.rollback()
    elif redis_status == AuctionStatus.ENDED.value:
        await finalize_auction(db, auction_id, force=True)
    elif redis_status == AuctionStatus.CANCELLED.value:
        await cancel_auction(db, auction_id)


# ---------------------------------------------------------------------------- bidding


def _live_state_from_result(result: dict[str, Any]) -> LiveAuctionState:
    highest_id = result.get("highest_bidder_id") or ""
    return LiveAuctionState(
        auction_id=int(result["auction_id"]),
        status=result.get("auction_status") or "",
        current_price=from_minor(result["current_price"]),
        min_next_bid=from_minor(result["min_next_bid"]),
        highest_bidder_id=int(highest_id) if highest_id else None,
        highest_bidder=result.get("highest_bidder_name") or None,
        bid_count=int(result.get("bid_count", 0)),
        end_time=from_ms(result["end_ms"]),
        server_time=from_ms(result["server_time_ms"]),
    )


async def place_bid(
    db: AsyncSession,
    user: User,
    auction_id: int,
    amount: Decimal,
    *,
    expected_current_price: Decimal | None = None,
    idempotency_key: str | None = None,
) -> BidPlacementResponse:
    if user.role == UserRole.ADMIN or not user.is_active:
        raise AppError("Unauthorized bidder.", "UNAUTHORIZED_BIDDER", 403)

    # Captured as plain values because the auction-not-loaded path below rolls back
    # this same session, which unconditionally expires every ORM object attached to
    # it (unlike commit, rollback ignores expire_on_commit) — including `user`, which
    # was loaded by the auth dependency on this session. Accessing user.id/user.name
    # after that would trigger a lazy reload outside of an awaited context and crash.
    bidder_id = user.id
    bidder_name = user.name

    bid_id = uuid.uuid4()
    call = dict(
        auction_id=auction_id,
        bidder_id=bidder_id,
        bidder_name=bidder_name,
        amount_minor=to_minor(amount),
        bid_id=str(bid_id),
        idempotency_key_value=idempotency_key,
        expected_minor=to_minor(expected_current_price) if expected_current_price is not None else None,
    )

    result = await redis_service.place_bid(**call)
    if result["code"] == "NOT_LOADED":
        await ensure_loaded(db, auction_id)  # raises 404 if the auction does not exist
        await db.rollback()  # release the read snapshot before the hot path
        result = await redis_service.place_bid(**call)
        if result["code"] == "NOT_LOADED":
            raise AppError("Auction state is temporarily unavailable. Please retry.", "AUCTION_STATE_UNAVAILABLE", 503)

    duplicate = bool(result.get("duplicate"))
    live = _live_state_from_result(result)
    recorded_bid_id = uuid.UUID(result["bid_id"])
    bid_time = from_ms(result["server_time_ms"])

    if not result["accepted"]:
        code = result["code"]
        status_code, message = REJECTIONS.get(code, (409, "Bid rejected."))
        if code == "BID_TOO_LOW" and live.bid_count == 0:
            message = "Bid must be at least the starting price."
        if not duplicate:
            await _persist_rejected_bid(
                db,
                bid_id=recorded_bid_id,
                auction_id=auction_id,
                bidder_id=bidder_id,
                amount=amount,
                reason=code,
                bid_time=bid_time,
                idempotency_key=idempotency_key,
            )
        raise AppError(
            message,
            code,
            status_code,
            details={
                "current_price": float(live.current_price),
                "min_next_bid": float(live.min_next_bid),
                "highest_bidder": live.highest_bidder,
                "duplicate": duplicate,
            },
        )

    accepted_amount = from_minor(result["amount"])
    bid_out = BidOut(
        id=recorded_bid_id,
        auction_id=auction_id,
        bidder_id=bidder_id,
        bidder_name=bidder_name,
        amount=accepted_amount,
        bid_time=bid_time,
        status=BidStatus.ACCEPTED,
    )

    if not duplicate:
        accepted = AcceptedBid(
            bid_id=recorded_bid_id,
            auction_id=auction_id,
            bidder_id=bidder_id,
            amount=accepted_amount,
            bid_time=bid_time,
            sequence=int(result["version"]),
            idempotency_key=idempotency_key,
        )
        try:
            await persist_accepted_bids(db, [accepted])
            await db.commit()
        except SQLAlchemyError:
            await db.rollback()
            logger.exception("Persisting bid %s failed; it remains in the Redis stream for reconciliation", bid_id)
        else:
            try:
                await redis_service.delete_stream_entries([result["stream_id"]])
            except RedisError:
                logger.warning("Could not remove persisted bid %s from stream; reconciler will skip it", bid_id)

        await publish_safely(
            auction_id,
            make_event(
                "BID_ACCEPTED",
                auction_id,
                current_price=float(live.current_price),
                min_next_bid=float(live.min_next_bid),
                highest_bidder=live.highest_bidder,
                highest_bidder_id=live.highest_bidder_id,
                bid_count=live.bid_count,
                end_time=live.end_time.isoformat().replace("+00:00", "Z"),
                epoch=int(result.get("epoch") or 0),
                seq=int(result["version"]),
                bid=bid_out.model_dump(mode="json"),
            ),
        )

    return BidPlacementResponse(
        message="Bid accepted." if not duplicate else "Duplicate request: bid was already accepted.",
        duplicate=duplicate,
        bid=bid_out,
        auction=live,
    )
