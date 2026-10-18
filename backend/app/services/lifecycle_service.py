"""Background worker that drives the UPCOMING -> LIVE -> ENDED lifecycle.

Runs in every API process but only the holder of a Redis leader lock does work,
so scaling the API horizontally never double-processes transitions.
"""

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import SessionLocal
from app.models import Auction, AuctionStatus
from app.services import auction_service
from app.services.redis_service import LIFECYCLE_LOCK_KEY, redis_service

logger = logging.getLogger(__name__)

BATCH_SIZE = 100


class LifecycleWorker:
    def __init__(self) -> None:
        self.owner = uuid.uuid4().hex
        self._last_reconcile = 0.0

    async def run(self) -> None:
        interval = settings.lifecycle_interval_seconds
        lock_ttl_ms = int(max(interval * 5, 5) * 1000)
        logger.info("Lifecycle worker started (owner=%s)", self.owner)
        try:
            while True:
                try:
                    if await redis_service.acquire_or_renew_lock(LIFECYCLE_LOCK_KEY, self.owner, lock_ttl_ms):
                        await self.tick()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Lifecycle tick failed")
                await asyncio.sleep(interval)
        finally:
            try:
                await redis_service.release_lock(LIFECYCLE_LOCK_KEY, self.owner)
            except Exception:
                pass

    async def tick(self) -> None:
        now = auction_service.utcnow()
        async with SessionLocal() as db:
            due_start = (
                await db.scalars(
                    select(Auction.id)
                    .where(
                        Auction.status == AuctionStatus.UPCOMING,
                        Auction.start_time <= now,
                        Auction.end_time > now,
                    )
                    .order_by(Auction.start_time)
                    .limit(BATCH_SIZE)
                )
            ).all()
            due_end = (
                await db.scalars(
                    select(Auction.id)
                    .where(Auction.status.in_(auction_service.ACTIVE_STATUSES), Auction.end_time <= now)
                    .order_by(Auction.end_time)
                    .limit(BATCH_SIZE)
                )
            ).all()

        for auction_id in due_start:
            await self._run(auction_service.start_auction, auction_id)
        for auction_id in due_end:
            await self._run(auction_service.finalize_auction, auction_id)

        if time.monotonic() - self._last_reconcile >= settings.reconcile_interval_seconds:
            self._last_reconcile = time.monotonic()
            await self.reconcile()

    async def reconcile(self) -> None:
        async with SessionLocal() as db:
            await auction_service.reconcile_stream(db, min_age_ms=settings.stream_reconcile_age_ms)
            live_ids = (
                await db.scalars(select(Auction.id).where(Auction.status == AuctionStatus.LIVE))
            ).all()
        for auction_id in live_ids:
            await self._run(auction_service.repair_live_state, auction_id)

    @staticmethod
    async def _run(operation: Callable[[AsyncSession, int], Awaitable[object]], auction_id: int) -> None:
        async with SessionLocal() as db:
            try:
                await operation(db, auction_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                await db.rollback()
                logger.exception("%s failed for auction %s", operation.__name__, auction_id)


lifecycle_worker = LifecycleWorker()
