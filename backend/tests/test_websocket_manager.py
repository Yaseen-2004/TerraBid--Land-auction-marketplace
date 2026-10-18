"""Unit tests for WebSocket fan-out (no external services required)."""

from app.config import settings
from app.services.websocket_service import Connection, ConnectionManager


class _FakeSocket:
    pass


def test_dispatch_reaches_only_the_matching_room():
    manager = ConnectionManager()
    watcher_a = Connection(_FakeSocket(), auction_id=1, user_id=None)
    watcher_b = Connection(_FakeSocket(), auction_id=2, user_id=7)
    manager.register(watcher_a)
    manager.register(watcher_b)

    manager.dispatch(1, '{"event":"BID_ACCEPTED"}')

    assert watcher_a.queue.qsize() == 1
    assert watcher_b.queue.qsize() == 0
    assert manager.connection_count() == 2

    manager.unregister(watcher_a)
    assert manager.connection_count(1) == 0


def test_slow_consumer_is_flagged_instead_of_blocking():
    manager = ConnectionManager()
    slow = Connection(_FakeSocket(), auction_id=1, user_id=None)
    manager.register(slow)
    for _ in range(settings.ws_send_queue_size + 5):
        manager.dispatch(1, "{}")
    assert slow.overflowed is True
    assert slow.queue.qsize() == settings.ws_send_queue_size
