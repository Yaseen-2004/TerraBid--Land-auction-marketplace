import logging
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import AppError
from app.core.security import decode_access_token
from app.database import get_db
from app.models import User, UserRole
from app.services.redis_service import redis_service

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_optional_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User | None:
    if credentials is None:
        return None
    payload = decode_access_token(credentials.credentials)
    user = await db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise AppError("Account not found or disabled.", "UNAUTHORIZED", 401)
    return user


async def get_current_user(user: Annotated[User | None, Depends(get_optional_user)]) -> User:
    if user is None:
        raise AppError(
            "Authentication required.", "UNAUTHORIZED", 401, headers={"WWW-Authenticate": "Bearer"}
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]


def require_roles(*roles: UserRole) -> Callable[..., Awaitable[User]]:
    async def _dependency(user: CurrentUser) -> User:
        if user.role not in roles:
            raise AppError("You do not have permission to perform this action.", "FORBIDDEN", 403)
        return user

    return _dependency


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def rate_limit(scope: str, limit: int, window_seconds: int, *, per_user: bool = False) -> Callable[..., Awaitable[None]]:
    """Distributed fixed-window rate limiter backed by Redis (shared across all API instances)."""

    async def _dependency(request: Request, user: OptionalUser) -> None:
        if not settings.rate_limit_enabled:
            return
        identity = f"user:{user.id}" if per_user and user is not None else f"ip:{_client_ip(request)}"
        key = f"ratelimit:{scope}:{identity}"
        try:
            count, ttl_ms = await redis_service.hit_rate_limit(key, window_seconds * 1000)
        except RedisError:
            logger.warning("Rate limiter unavailable; allowing request")
            return
        if count > limit:
            retry_after = max(1, (ttl_ms + 999) // 1000)
            raise AppError(
                "Too many requests. Please slow down.",
                "RATE_LIMITED",
                429,
                details={"retry_after_seconds": retry_after},
                headers={"Retry-After": str(retry_after)},
            )

    return _dependency
