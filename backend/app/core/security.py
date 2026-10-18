import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.config import settings
from app.core.errors import AppError

_hasher = PasswordHasher()  # Argon2id with library-recommended parameters
_DUMMY_HASH = _hasher.hash("timing-equalisation-placeholder")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    try:
        return _hasher.verify(hashed_password, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def dummy_verify(password: str) -> None:
    """Spend the same time as a real verification so login can't be used to enumerate emails."""
    verify_password(password, _DUMMY_HASH)


def create_access_token(user_id: int, role: str) -> tuple[str, int]:
    now = datetime.now(UTC)
    lifetime = timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "iss": settings.jwt_issuer,
        "iat": now,
        "nbf": now,
        "exp": now + lifetime,
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, int(lifetime.total_seconds())


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            leeway=10,
            options={"require": ["exp", "iat", "sub", "iss"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AppError("Your session has expired. Please log in again.", "TOKEN_EXPIRED", 401) from exc
    except jwt.InvalidTokenError as exc:
        raise AppError("Invalid authentication token.", "INVALID_TOKEN", 401) from exc

    if payload.get("type") != "access" or not str(payload.get("sub", "")).isdigit():
        raise AppError("Invalid authentication token.", "INVALID_TOKEN", 401)
    return payload
