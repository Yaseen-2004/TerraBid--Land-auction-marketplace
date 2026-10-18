import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import settings
from app.dependencies import DbSession
from app.services.redis_service import redis_service
from app.services.websocket_service import manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/config")
async def public_config() -> dict:
    """Public, non-secret client configuration."""
    return {
        "app_name": settings.app_name,
        "esri_api_key": settings.esri_api_key,
        "currency": "INR",
    }


@router.get("/health")
async def health(db: DbSession) -> JSONResponse:
    checks = {"database": "ok", "redis": "ok"}
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        logger.warning("Health check: database unavailable", exc_info=True)
        checks["database"] = "unavailable"
    try:
        await redis_service.ping()
    except Exception:
        logger.warning("Health check: redis unavailable", exc_info=True)
        checks["redis"] = "unavailable"
    healthy = all(value == "ok" for value in checks.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ok" if healthy else "degraded", **checks, "websocket_connections": manager.connection_count()},
    )
