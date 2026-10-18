import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import BidStatus
from app.schemas.common import Money, PositiveMoney


class BidCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: PositiveMoney
    # Only used to choose between "outbid" and "too low" error messages; never trusted for validation.
    expected_current_price: Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)] | None = None


class BidOut(BaseModel):
    id: uuid.UUID
    auction_id: int
    bidder_id: int
    bidder_name: str
    amount: Money
    bid_time: datetime
    status: BidStatus
    rejection_reason: str | None = None


class LiveAuctionState(BaseModel):
    auction_id: int
    status: str
    current_price: Money
    min_next_bid: Money
    highest_bidder_id: int | None
    highest_bidder: str | None
    bid_count: int
    end_time: datetime
    server_time: datetime


class BidPlacementResponse(BaseModel):
    success: bool = True
    message: str
    duplicate: bool = False
    bid: BidOut
    auction: LiveAuctionState


class BidderSummary(BaseModel):
    bidder_id: int
    name: str
    email: str
    bid_count: int
    highest_amount: Money
    last_bid_time: datetime
