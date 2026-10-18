import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.database import engine
from app.routers import admin, auctions, auth, bids, properties, system
from app.services.lifecycle_service import lifecycle_worker
from app.services.redis_service import redis_service
from app.services.websocket_service import manager
from app.websocket import routes as websocket_routes

logger = logging.getLogger("app")

_background_tasks: list[asyncio.Task] = []


async def startup() -> None:
    await redis_service.connect()
    if settings.run_background_tasks:
        _background_tasks.append(asyncio.create_task(manager.listen(redis_service), name="ws-pubsub-relay"))
        _background_tasks.append(asyncio.create_task(lifecycle_worker.run(), name="auction-lifecycle"))


async def shutdown() -> None:
    for task in _background_tasks:
        task.cancel()
    for task in _background_tasks:
        with suppress(asyncio.CancelledError, Exception):
            await task
    _background_tasks.clear()
    await redis_service.close()
    await engine.dispose()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    await startup()
    logger.info("%s started (%s)", settings.app_name, settings.environment)
    try:
        yield
    finally:
        await shutdown()


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="Real-time geospatial land auction platform",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
    expose_headers=["X-Request-ID", "Retry-After"],
    max_age=600,
)


@app.middleware("http")
async def request_context(request: Request, call_next) -> Response:
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    logger.info(
        "%s %s -> %s (%.1f ms) rid=%s", request.method, request.url.path, response.status_code, elapsed_ms, request_id
    )
    return response


register_exception_handlers(app)

app.include_router(system.router)
app.include_router(auth.router)
app.include_router(properties.router)
app.include_router(auctions.router)
app.include_router(bids.router)
app.include_router(admin.router)
app.include_router(websocket_routes.router)
