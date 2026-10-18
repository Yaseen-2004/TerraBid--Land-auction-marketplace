from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Query

from app.config import settings
from app.core.errors import AppError
from app.dependencies import CurrentUser, DbSession, OptionalUser, rate_limit
from app.models import UserRole
from app.schemas.bid import BidCreate, BidOut, BidPlacementResponse
from app.services import auction_service

router = APIRouter(prefix="/api/auctions", tags=["bids"])

AuctionId = Annotated[int, Path(gt=0)]


@router.post(
    "/{auction_id}/bid",
    response_model=BidPlacementResponse,
    dependencies=[Depends(rate_limit("bids", settings.rate_limit_bids_per_10s, 10, per_user=True))],
    responses={
        403: {"description": "Unauthorized bidder"},
        404: {"description": "Auction does not exist"},
        409: {"description": "Auction not live / ended / outbid"},
        422: {"description": "Bid below the minimum increment"},
    },
)
async def place_bid(
    payload: BidCreate,
    db: DbSession,
    user: CurrentUser,
    auction_id: AuctionId,
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", max_length=128, pattern=r"^[A-Za-z0-9_\-:.]+$"),
    ] = None,
) -> BidPlacementResponse:
    return await auction_service.place_bid(
        db,
        user,
        auction_id,
        payload.amount,
        expected_current_price=payload.expected_current_price,
        idempotency_key=idempotency_key,
    )


@router.get("/{auction_id}/bids", response_model=list[BidOut])
async def list_bids(
    db: DbSession,
    user: OptionalUser,
    auction_id: AuctionId,
    include_rejected: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[BidOut]:
    if include_rejected and (user is None or user.role != UserRole.ADMIN):
        raise AppError("Only administrators can view rejected bids.", "FORBIDDEN", 403)
    await auction_service.get_auction(db, auction_id)
    return await auction_service.list_bids(
        db, auction_id, include_rejected=include_rejected, limit=limit, offset=offset
    )
