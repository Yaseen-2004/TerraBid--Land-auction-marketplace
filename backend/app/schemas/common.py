from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import AfterValidator, AwareDatetime, BaseModel, Field, PlainSerializer


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


# Monetary values are Decimal internally and serialised as JSON numbers.
Money = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]
PositiveMoney = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=2)]
UTCDateTime = Annotated[AwareDatetime, AfterValidator(_to_utc)]


class ErrorResponse(BaseModel):
    success: bool = False
    message: str
    error_code: str
    details: Any | None = None


class MessageResponse(BaseModel):
    success: bool = True
    message: str
