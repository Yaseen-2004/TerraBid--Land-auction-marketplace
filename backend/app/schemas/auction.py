from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import AuctionStatus, PropertyStatus
from app.schemas.common import Money, PositiveMoney, UTCDateTime


class AuctionSchedule(BaseModel):
    """Auction window supplied together with a new property."""

    model_config = ConfigDict(extra="forbid")

    start_time: UTCDateTime
    end_time: UTCDateTime
    starting_price: PositiveMoney | None = Field(default=None, description="Defaults to the property base price")
    minimum_increment: PositiveMoney

    @model_validator(mode="after")
    def _check_window(self) -> "AuctionSchedule":
        if self.end_time <= self.start_time:
            raise ValueError("Auction end time must be after the start time.")
        return self


class AuctionCreate(AuctionSchedule):
    property_id: int = Field(gt=0)


class AuctionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_time: UTCDateTime | None = None
    end_time: UTCDateTime | None = None
    starting_price: PositiveMoney | None = None
    minimum_increment: PositiveMoney | None = None


class PropertyBrief(BaseModel):
    id: int
    title: str
    location: str
    status: PropertyStatus
    created_by: int


class AuctionOut(BaseModel):
    id: int
    property_id: int
    status: AuctionStatus
    starting_price: Money
    current_price: Money
    minimum_increment: Money
    min_next_bid: Money
    start_time: datetime
    end_time: datetime
    bid_count: int
    highest_bidder_id: int | None = None
    highest_bidder: str | None = None
    winner_id: int | None = None
    winner_name: str | None = None
    created_at: datetime
    updated_at: datetime
    property: PropertyBrief | None = None
