from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.core.errors import AppError
from app.core.security import create_access_token, dummy_verify, hash_password, verify_password
from app.dependencies import CurrentUser, DbSession, rate_limit
from app.models import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])

_auth_rate_limit = Depends(rate_limit("auth", settings.rate_limit_auth_per_minute, 60))


def _token_response(user: User) -> TokenResponse:
    token, expires_in = create_access_token(user.id, user.role.value)
    return TokenResponse(access_token=token, expires_in=expires_in, user=UserOut.model_validate(user))


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED, dependencies=[_auth_rate_limit])
async def register(payload: RegisterRequest, db: DbSession) -> TokenResponse:
    duplicate = AppError("An account with this email already exists.", "EMAIL_ALREADY_REGISTERED", 409)
    if await db.scalar(select(User.id).where(User.email == payload.email)) is not None:
        raise duplicate

    hashed = await run_in_threadpool(hash_password, payload.password)
    user = User(name=payload.name, email=payload.email, hashed_password=hashed, role=payload.role)
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise duplicate from exc
    await db.refresh(user)
    return _token_response(user)


@router.post("/login", response_model=TokenResponse, dependencies=[_auth_rate_limit])
async def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    invalid = AppError("Invalid email or password.", "INVALID_CREDENTIALS", 401)
    user = await db.scalar(select(User).where(User.email == payload.email))
    if user is None:
        await run_in_threadpool(dummy_verify, payload.password)
        raise invalid
    if not await run_in_threadpool(verify_password, payload.password, user.hashed_password):
        raise invalid
    if not user.is_active:
        raise AppError("This account has been disabled.", "ACCOUNT_DISABLED", 403)
    return _token_response(user)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> User:
    return user
