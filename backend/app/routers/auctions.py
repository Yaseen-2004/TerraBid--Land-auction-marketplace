from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status

from app.config import settings
from app.dependencies import DbSession, rate_limit, require_roles
from app.models import AuctionStatus, User, UserRole
from app.schemas.auction import AuctionCreate, AuctionOut, AuctionUpdate
from app.services import auction_service

router = APIRouter(prefix="/api/auctions", tags=["auctions"])

AuctionManager = Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.SELLER))]
Admin = Annotated[User, Depends(require_roles(UserRole.ADMIN))]
AuctionId = Annotated[int, Path(gt=0)]
_write_rate_limit = Depends(rate_limit("writes", settings.rate_limit_writes_per_minute, 60, per_user=True))


@router.get("", response_model=list[AuctionOut])
async def list_auctions(
    db: DbSession,
    status_filter: Annotated[list[AuctionStatus] | None, Query(alias="status")] = None,
    property_id: Annotated[int | None, Query(gt=0)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AuctionOut]:
    return await auction_service.list_auctions(
        db, statuses=status_filter, property_id=property_id, limit=limit, offset=offset
    )


@router.get("/{auction_id}", response_model=AuctionOut)
async def get_auction(db: DbSession, auction_id: AuctionId) -> AuctionOut:
    return await auction_service.get_auction_view(db, auction_id)


@router.post("", response_model=AuctionOut, status_code=status.HTTP_201_CREATED, dependencies=[_write_rate_limit])
async def create_auction(payload: AuctionCreate, db: DbSession, user: AuctionManager) -> AuctionOut:
    return await auction_service.create_auction(db, user, payload)


@router.put("/{auction_id}", response_model=AuctionOut, dependencies=[_write_rate_limit])
async def update_auction(payload: AuctionUpdate, db: DbSession, user: AuctionManager, auction_id: AuctionId) -> AuctionOut:
    return await auction_service.update_auction(db, user, auction_id, payload)


@router.put("/{auction_id}/start", response_model=AuctionOut)
async def start_auction(db: DbSession, _: Admin, auction_id: AuctionId) -> AuctionOut:
    await auction_service.start_auction(db, auction_id, manual=True)
    return await auction_service.get_auction_view(db, auction_id)


@router.put("/{auction_id}/end", response_model=AuctionOut)
async def end_auction(db: DbSession, _: Admin, auction_id: AuctionId) -> AuctionOut:
    await auction_service.finalize_auction(db, auction_id, manual=True)
    return await auction_service.get_auction_view(db, auction_id)


@router.put("/{auction_id}/cancel", response_model=AuctionOut)
async def cancel_auction(db: DbSession, _: Admin, auction_id: AuctionId) -> AuctionOut:
    await auction_service.cancel_auction(db, auction_id)
    return await auction_service.get_auction_view(db, auction_id)
