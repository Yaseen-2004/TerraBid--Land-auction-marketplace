from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status

from app.config import settings
from app.core.errors import AppError
from app.dependencies import DbSession, rate_limit, require_roles
from app.models import AuctionStatus, PropertyStatus, User, UserRole
from app.schemas.property import PropertyCreate, PropertyOut, PropertyUpdate
from app.services import property_service

router = APIRouter(prefix="/api/properties", tags=["properties"])

PropertyManager = Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.SELLER))]
_write_rate_limit = Depends(rate_limit("writes", settings.rate_limit_writes_per_minute, 60, per_user=True))


def _parse_bbox(raw: str | None) -> tuple[float, float, float, float] | None:
    if raw is None:
        return None
    try:
        min_lon, min_lat, max_lon, max_lat = (float(part) for part in raw.split(","))
    except ValueError as exc:
        raise AppError("bbox must be 'minLon,minLat,maxLon,maxLat'.", "INVALID_BBOX", 422) from exc
    if not (-180 <= min_lon < max_lon <= 180 and -90 <= min_lat < max_lat <= 90):
        raise AppError("bbox coordinates are out of range.", "INVALID_BBOX", 422)
    return min_lon, min_lat, max_lon, max_lat


@router.get("", response_model=list[PropertyOut])
async def list_properties(
    db: DbSession,
    bbox: Annotated[str | None, Query(description="minLon,minLat,maxLon,maxLat", max_length=100)] = None,
    q: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    auction_status: Annotated[list[AuctionStatus] | None, Query()] = None,
    status_filter: Annotated[list[PropertyStatus] | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[PropertyOut]:
    return await property_service.list_properties(
        db,
        bbox=_parse_bbox(bbox),
        search=q,
        auction_statuses=auction_status,
        property_statuses=status_filter,
        limit=limit,
        offset=offset,
    )


@router.get("/{property_id}", response_model=PropertyOut)
async def get_property(db: DbSession, property_id: Annotated[int, Path(gt=0)]) -> PropertyOut:
    return await property_service.get_property(db, property_id)


@router.post("", response_model=PropertyOut, status_code=status.HTTP_201_CREATED, dependencies=[_write_rate_limit])
async def create_property(payload: PropertyCreate, db: DbSession, user: PropertyManager) -> PropertyOut:
    return await property_service.create_property(db, user, payload)


@router.put("/{property_id}", response_model=PropertyOut, dependencies=[_write_rate_limit])
async def update_property(
    payload: PropertyUpdate, db: DbSession, user: PropertyManager, property_id: Annotated[int, Path(gt=0)]
) -> PropertyOut:
    return await property_service.update_property(db, user, property_id, payload)


@router.delete("/{property_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_write_rate_limit])
async def delete_property(db: DbSession, user: PropertyManager, property_id: Annotated[int, Path(gt=0)]) -> Response:
    await property_service.delete_property(db, user, property_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
