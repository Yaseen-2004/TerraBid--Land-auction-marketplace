"""WebSocket connection management.

Every API instance subscribes to the Redis pattern `auction_events:*` and fans
events out to its own local sockets, so a bid accepted on any instance reaches
every watcher regardless of which instance they are connected to.

Each connection has a bounded outbound queue drained by its own sender task:
a slow client can never block broadcasting to other clients. If a client falls
too far behind it is disconnected and resynchronises with a fresh snapshot.
"""

import asyncio
import json
import logging
from collections import defaultdict

from fastapi import WebSocket

from app.config import settings
from app.services.redis_service import EVENT_CHANNEL_PREFIX, RedisService

logger = logging.getLogger(__name__)

RESYNC_MESSAGE = json.dumps({"event": "RESYNC", "reason": "event stream interrupted"})


class Connection:
    __slots__ = ("websocket", "auction_id", "user_id", "queue", "overflowed")

    def __init__(self, websocket: WebSocket, auction_id: int, user_id: int | None) -> None:
        self.websocket = websocket
        self.auction_id = auction_id
        self.user_id = user_id
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=settings.ws_send_queue_size)
        self.overflowed = False

    def enqueue(self, message: str) -> None:
        try:
            self.queue.put_nowait(message)
        except asyncio.QueueFull:
            self.overflowed = True


class ConnectionManager:
    def __init__(self) -> None:
        self._rooms: dict[int, set[Connection]] = defaultdict(set)

    def register(self, connection: Connection) -> None:
        self._rooms[connection.auction_id].add(connection)

    def unregister(self, connection: Connection) -> None:
        room = self._rooms.get(connection.auction_id)
        if room is None:
            return
        room.discard(connection)
        if not room:
            self._rooms.pop(connection.auction_id, None)

    def connection_count(self, auction_id: int | None = None) -> int:
        if auction_id is not None:
            return len(self._rooms.get(auction_id, ()))
        return sum(len(room) for room in self._rooms.values())

    def dispatch(self, auction_id: int, message: str) -> None:
        for connection in tuple(self._rooms.get(auction_id, ())):
            connection.enqueue(message)

    def dispatch_all(self, message: str) -> None:
        for room in tuple(self._rooms.values()):
            for connection in tuple(room):
                connection.enqueue(message)

    async def listen(self, redis: RedisService) -> None:
        """Relay Redis pub/sub events to local sockets, reconnecting with backoff."""
        backoff = 1.0
        first_subscription = True
        while True:
            pubsub = None
            try:
                pubsub = redis.client.pubsub(ignore_subscribe_messages=True)
                await pubsub.psubscribe(f"{EVENT_CHANNEL_PREFIX}*")
                if not first_subscription:
                    # Events may have been missed while disconnected: ask clients to refetch state.
                    self.dispatch_all(RESYNC_MESSAGE)
                first_subscription = False
                backoff = 1.0
                async for message in pubsub.listen():
                    if message.get("type") != "pmessage":
                        continue
                    try:
                        auction_id = int(str(message["channel"]).rsplit(":", 1)[1])
                    except (IndexError, ValueError):
                        continue
                    self.dispatch(auction_id, message["data"])
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Pub/sub listener disconnected; reconnecting in %.0fs", backoff, exc_info=True)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
            finally:
                if pubsub is not None:
                    try:
                        await pubsub.aclose()
                    except Exception:
                        pass


manager = ConnectionManager()
