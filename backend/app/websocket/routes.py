import asyncio
import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import settings
from app.core.errors import AppError
from app.core.security import decode_access_token
from app.database import SessionLocal
from app.models import User
from app.services import auction_service
from app.services.redis_service import dumps
from app.services.websocket_service import Connection, manager

logger = logging.getLogger(__name__)

router = APIRouter()

CLOSE_UNAUTHORIZED = 4401
CLOSE_NOT_FOUND = 4404
CLOSE_TRY_AGAIN = 1013
MAX_CLIENT_MESSAGE_BYTES = 1024


async def _reject(websocket: WebSocket, code: int, reason: str) -> None:
    # Accept first so the browser receives the application close code instead of a bare handshake failure.
    await websocket.accept()
    await websocket.close(code=code, reason=reason)


async def _sender(connection: Connection, token_exp: float | None) -> None:
    websocket = connection.websocket
    try:
        while True:
            try:
                message = await asyncio.wait_for(connection.queue.get(), timeout=settings.ws_heartbeat_seconds)
            except TimeoutError:
                if token_exp is not None and time.time() >= token_exp:
                    await websocket.close(code=CLOSE_UNAUTHORIZED, reason="Token expired")
                    return
                message = dumps({"event": "HEARTBEAT", "timestamp": auction_service.iso_now()})
            await websocket.send_text(message)
            if connection.overflowed:
                await websocket.close(code=CLOSE_TRY_AGAIN, reason="Client too slow; reconnect to resync")
                return
    except (WebSocketDisconnect, RuntimeError):
        return
    except Exception:
        logger.debug("WebSocket sender stopped", exc_info=True)


@router.websocket("/ws/auctions/{auction_id}")
async def auction_socket(websocket: WebSocket, auction_id: int) -> None:
    token = websocket.query_params.get("token")
    user_id: int | None = None
    token_exp: float | None = None

    if token:
        try:
            payload = decode_access_token(token)
        except AppError as exc:
            await _reject(websocket, CLOSE_UNAUTHORIZED, exc.message)
            return
        user_id, token_exp = int(payload["sub"]), float(payload["exp"])
    elif not settings.ws_allow_anonymous:
        await _reject(websocket, CLOSE_UNAUTHORIZED, "Authentication required")
        return

    async with SessionLocal() as db:
        if user_id is not None:
            user = await db.get(User, user_id)
            if user is None or not user.is_active:
                await _reject(websocket, CLOSE_UNAUTHORIZED, "Account not found or disabled")
                return
        try:
            await auction_service.get_auction(db, auction_id)
        except AppError:
            await _reject(websocket, CLOSE_NOT_FOUND, "Auction does not exist")
            return

    await websocket.accept()
    connection = Connection(websocket, auction_id, user_id)
    # Register before building the snapshot so no event can fall between the two;
    # clients discard queued events older than the snapshot using (epoch, seq).
    manager.register(connection)
    sender: asyncio.Task | None = None
    try:
        async with SessionLocal() as db:
            snapshot = await auction_service.get_snapshot(db, auction_id)
        await websocket.send_text(dumps(snapshot))
        sender = asyncio.create_task(_sender(connection, token_exp))

        while True:
            raw = await websocket.receive_text()
            if len(raw) > MAX_CLIENT_MESSAGE_BYTES:
                continue
            try:
                message = json.loads(raw)
            except ValueError:
                continue
            kind = message.get("type") if isinstance(message, dict) else None
            if kind == "ping":
                connection.enqueue(dumps({"event": "PONG", "timestamp": auction_service.iso_now()}))
            elif kind == "sync":
                async with SessionLocal() as db:
                    connection.enqueue(dumps(await auction_service.get_snapshot(db, auction_id)))
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WebSocket error for auction %s", auction_id)
    finally:
        manager.unregister(connection)
        if sender is not None:
            sender.cancel()
