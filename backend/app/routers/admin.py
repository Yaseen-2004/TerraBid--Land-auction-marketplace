from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import func, select

from app.core.errors import AppError
from app.dependencies import DbSession, require_roles
from app.models import Auction, AuctionStatus, Bid, BidStatus, Property, User, UserRole
from app.schemas.admin import DashboardStats
from app.schemas.auth import UserAdminUpdate, UserOut
from app.schemas.bid import BidderSummary
from app.services import auction_service

Admin = Annotated[User, Depends(require_roles(UserRole.ADMIN))]

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/stats", response_model=DashboardStats)
async def dashboard_stats(db: DbSession, _: Admin) -> DashboardStats:
    auction_counts = dict(
        (await db.execute(select(Auction.status, func.count()).group_by(Auction.status))).all()
    )
    bid_counts = dict((await db.execute(select(Bid.status, func.count()).group_by(Bid.status))).all())
    sales = await db.scalar(
        select(func.coalesce(func.sum(Auction.current_price), 0)).where(
            Auction.status == AuctionStatus.ENDED, Auction.winner_id.is_not(None)
        )
    )
    return DashboardStats(
        total_properties=await db.scalar(select(func.count()).select_from(Property)) or 0,
        active_auctions=auction_counts.get(AuctionStatus.LIVE, 0),
        upcoming_auctions=auction_counts.get(AuctionStatus.UPCOMING, 0),
        completed_auctions=auction_counts.get(AuctionStatus.ENDED, 0),
        cancelled_auctions=auction_counts.get(AuctionStatus.CANCELLED, 0),
        registered_users=await db.scalar(select(func.count()).select_from(User)) or 0,
        total_bids=bid_counts.get(BidStatus.ACCEPTED, 0),
        rejected_bids=bid_counts.get(BidStatus.REJECTED, 0),
        total_sales_value=sales or 0,
    )


@router.get("/users", response_model=list[UserOut])
async def list_users(
    db: DbSession,
    _: Admin,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[User]:
    return list((await db.scalars(select(User).order_by(User.created_at.desc()).limit(limit).offset(offset))).all())


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    payload: UserAdminUpdate, db: DbSession, admin: Admin, user_id: Annotated[int, Path(gt=0)]
) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise AppError("User does not exist.", "USER_NOT_FOUND", 404)
    if user.id == admin.id:
        raise AppError("Administrators cannot change their own role or status.", "FORBIDDEN", 403)
    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
    await db.commit()
    await db.refresh(user)
    return user


@router.get("/auctions/{auction_id}/bidders", response_model=list[BidderSummary])
async def auction_bidders(db: DbSession, _: Admin, auction_id: Annotated[int, Path(gt=0)]) -> list[BidderSummary]:
    await auction_service.get_auction(db, auction_id)
    rows = await db.execute(
        select(User.id, User.name, User.email, func.count(Bid.id), func.max(Bid.amount), func.max(Bid.bid_time))
        .join(Bid, Bid.bidder_id == User.id)
        .where(Bid.auction_id == auction_id, Bid.status == BidStatus.ACCEPTED)
        .group_by(User.id)
        .order_by(func.max(Bid.amount).desc())
    )
    return [
        BidderSummary(
            bidder_id=uid, name=name, email=email, bid_count=count, highest_amount=highest, last_bid_time=last
        )
        for uid, name, email, count, highest, last in rows.all()
    ]
