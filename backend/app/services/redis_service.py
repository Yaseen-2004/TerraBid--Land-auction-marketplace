"""Redis access layer: connection pooling, Lua scripts, pub/sub publishing and the bid persistence stream."""

import asyncio
import json
import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from redis.asyncio import BlockingConnectionPool, Redis
from redis.commands.core import AsyncScript

from app.config import settings

logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "redis"
BID_STREAM_KEY = "bids:stream"
EVENT_CHANNEL_PREFIX = "auction_events:"
LIFECYCLE_LOCK_KEY = "lock:auction-lifecycle"


def state_key(auction_id: int) -> str:
    # The {id} hash tag keeps all keys of one auction in the same cluster slot.
    return f"auction:{{{auction_id}}}"


def idempotency_key(auction_id: int) -> str:
    return f"auction:{{{auction_id}}}:idem"


def event_channel(auction_id: int) -> str:
    return f"{EVENT_CHANNEL_PREFIX}{auction_id}"


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"Unserialisable type {type(value)!r}")


def dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, default=_json_default, separators=(",", ":"))


class RedisService:
    def __init__(self) -> None:
        self._client: Redis | None = None
        self._bid: AsyncScript | None = None
        self._hydrate: AsyncScript | None = None
        self._transition: AsyncScript | None = None
        self._lock: AsyncScript | None = None
        self._unlock: AsyncScript | None = None
        self._rate_limit: AsyncScript | None = None

    @property
    def client(self) -> Redis:
        if self._client is None:
            raise RuntimeError("Redis is not connected")
        return self._client

    async def connect(self, url: str | None = None, attempts: int = 10) -> None:
        pool = BlockingConnectionPool.from_url(
            url or settings.redis_url,
            max_connections=settings.redis_max_connections,
            timeout=10,
            decode_responses=True,
            health_check_interval=30,
            socket_keepalive=True,
            retry_on_timeout=True,
        )
        client = Redis(connection_pool=pool)
        delay = 0.5
        for attempt in range(1, attempts + 1):
            try:
                await client.ping()
                break
            except Exception:
                if attempt == attempts:
                    await client.aclose(close_connection_pool=True)
                    raise
                logger.warning("Redis not reachable (attempt %s/%s), retrying in %.1fs", attempt, attempts, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 5)

        self._client = client
        # register_script uses EVALSHA and transparently reloads scripts after a Redis restart.
        self._bid = client.register_script((SCRIPT_DIR / "bid.lua").read_text(encoding="utf-8"))
        self._hydrate = client.register_script((SCRIPT_DIR / "hydrate.lua").read_text(encoding="utf-8"))
        self._transition = client.register_script((SCRIPT_DIR / "transition.lua").read_text(encoding="utf-8"))
        self._lock = client.register_script((SCRIPT_DIR / "lock.lua").read_text(encoding="utf-8"))
        self._unlock = client.register_script((SCRIPT_DIR / "unlock.lua").read_text(encoding="utf-8"))
        self._rate_limit = client.register_script((SCRIPT_DIR / "rate_limit.lua").read_text(encoding="utf-8"))
        logger.info("Connected to Redis")

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose(close_connection_pool=True)
            self._client = None

    async def ping(self) -> bool:
        return bool(await self.client.ping())

    # ------------------------------------------------------------------ auction state

    async def place_bid(
        self,
        *,
        auction_id: int,
        bidder_id: int,
        bidder_name: str,
        amount_minor: int,
        bid_id: str,
        idempotency_key_value: str | None,
        expected_minor: int | None,
    ) -> dict[str, Any]:
        raw = await self._bid(  # type: ignore[misc]
            keys=[state_key(auction_id), idempotency_key(auction_id), BID_STREAM_KEY],
            args=[
                auction_id,
                bidder_id,
                bidder_name,
                amount_minor,
                bid_id,
                idempotency_key_value or "",
                "" if expected_minor is None else expected_minor,
            ],
        )
        return json.loads(raw)

    async def hydrate(self, auction_id: int, mapping: dict[str, str], ttl_seconds: int = 0) -> bool:
        args: list[Any] = [ttl_seconds]
        for field, value in mapping.items():
            args.extend([field, value])
        created = await self._hydrate(keys=[state_key(auction_id)], args=args)  # type: ignore[misc]
        return bool(created)

    async def transition(
        self, auction_id: int, status: str, *, start_ms: int | None = None, end_ms: int | None = None
    ) -> dict[str, Any]:
        raw = await self._transition(  # type: ignore[misc]
            keys=[state_key(auction_id)],
            args=[status, "" if start_ms is None else start_ms, "" if end_ms is None else end_ms],
        )
        return json.loads(raw)

    async def get_state(self, auction_id: int) -> dict[str, str] | None:
        state = await self.client.hgetall(state_key(auction_id))
        return state or None

    async def get_states(self, auction_ids: list[int]) -> dict[int, dict[str, str]]:
        if not auction_ids:
            return {}
        async with self.client.pipeline(transaction=False) as pipe:
            for auction_id in auction_ids:
                pipe.hgetall(state_key(auction_id))
            results = await pipe.execute()
        return {aid: state for aid, state in zip(auction_ids, results, strict=True) if state}

    async def expire_auction(self, auction_id: int, ttl_seconds: int) -> None:
        async with self.client.pipeline(transaction=False) as pipe:
            pipe.expire(state_key(auction_id), ttl_seconds)
            pipe.expire(idempotency_key(auction_id), ttl_seconds)
            await pipe.execute()

    async def delete_auction_state(self, auction_id: int) -> None:
        await self.client.delete(state_key(auction_id), idempotency_key(auction_id))

    # ------------------------------------------------------------------ events

    async def publish_event(self, auction_id: int, payload: dict[str, Any]) -> None:
        await self.client.publish(event_channel(auction_id), dumps(payload))

    # ------------------------------------------------------------------ persistence stream

    async def read_bid_stream(self, start: str = "-", count: int = 500) -> list[tuple[str, dict[str, str]]]:
        return await self.client.xrange(BID_STREAM_KEY, min=start, max="+", count=count)

    async def delete_stream_entries(self, entry_ids: list[str]) -> None:
        if entry_ids:
            await self.client.xdel(BID_STREAM_KEY, *entry_ids)

    # ------------------------------------------------------------------ locks & rate limits

    async def acquire_or_renew_lock(self, key: str, owner: str, ttl_ms: int) -> bool:
        return bool(await self._lock(keys=[key], args=[owner, ttl_ms]))  # type: ignore[misc]

    async def release_lock(self, key: str, owner: str) -> None:
        await self._unlock(keys=[key], args=[owner])  # type: ignore[misc]

    async def hit_rate_limit(self, key: str, window_ms: int) -> tuple[int, int]:
        count, ttl = await self._rate_limit(keys=[key], args=[window_ms])  # type: ignore[misc]
        return int(count), int(ttl)


redis_service = RedisService()
