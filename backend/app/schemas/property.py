from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.core.geo import MAX_WKT_LENGTH
from app.models.enums import PropertyStatus
from app.schemas.auction import AuctionOut, AuctionSchedule
from app.schemas.common import Money, PositiveMoney

Area = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=2)]


class _PropertyFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("title", "location", "description", mode="before", check_fields=False)
    @classmethod
    def _strip(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("image_url", mode="after", check_fields=False)
    @classmethod
    def _url_to_str(cls, value: Any) -> Any:
        return str(value) if value is not None else None


class PropertyCreate(_PropertyFields):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(default="", max_length=5000)
    location: str = Field(min_length=2, max_length=255)
    area: Area | None = Field(default=None, description="Square feet; computed from the polygon when omitted")
    base_price: PositiveMoney
    image_url: HttpUrl | None = None
    wkt: str = Field(min_length=10, max_length=MAX_WKT_LENGTH)
    auction: AuctionSchedule | None = None


class PropertyUpdate(_PropertyFields):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    location: str | None = Field(default=None, min_length=2, max_length=255)
    area: Area | None = None
    base_price: PositiveMoney | None = None
    image_url: HttpUrl | None = None
    wkt: str | None = Field(default=None, min_length=10, max_length=MAX_WKT_LENGTH)


class PropertyOut(BaseModel):
    id: int
    title: str
    description: str
    location: str
    area: Money | None
    base_price: Money
    image_url: str | None
    status: PropertyStatus
    created_by: int
    created_at: datetime
    updated_at: datetime
    geometry: dict[str, Any]
    wkt: str
    centroid: tuple[float, float] = Field(description="[latitude, longitude] of a point inside the polygon")
    auction: AuctionOut | None = None
