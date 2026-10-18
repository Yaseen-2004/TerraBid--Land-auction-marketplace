import json
import logging
from decimal import Decimal

from geoalchemy2 import WKTElement
from redis.exceptions import RedisError
from shapely.geometry import Polygon
from sqlalchemy import Select, delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.geo import SRID, parse_polygon_wkt
from app.models import Auction, AuctionStatus, Bid, Property, PropertyStatus, User
from app.schemas.property import PropertyCreate, PropertyOut, PropertyUpdate
from app.services import auction_service
from app.services.permissions import ensure_can_manage_property
from app.services.redis_service import redis_service

logger = logging.getLogger(__name__)

SQFT_PER_SQM = Decimal("10.76391041671")
_AUCTION_PRIORITY = {AuctionStatus.LIVE: 0, AuctionStatus.UPCOMING: 1, AuctionStatus.ENDED: 2, AuctionStatus.CANCELLED: 3}


def _property_select() -> Select:
    point = func.ST_PointOnSurface(Property.geometry)
    return select(
        Property,
        func.ST_AsGeoJSON(Property.geometry, 7).label("geojson"),
        func.ST_AsText(Property.geometry).label("wkt"),
        func.ST_Y(point).label("lat"),
        func.ST_X(point).label("lon"),
    )


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def _serialise(db: AsyncSession, rows: list) -> list[PropertyOut]:
    if not rows:
        return []
    property_ids = [row[0].id for row in rows]
    auctions = (
        await db.scalars(
            select(Auction).where(Auction.property_id.in_(property_ids)).order_by(Auction.created_at.desc())
        )
    ).all()

    # Show the most relevant auction per property: live > upcoming > most recent closed one.
    chosen: dict[int, Auction] = {}
    for auction in auctions:
        current = chosen.get(auction.property_id)
        if current is None or _AUCTION_PRIORITY[auction.status] < _AUCTION_PRIORITY[current.status]:
            chosen[auction.property_id] = auction
    views = await auction_service.build_auction_views(db, list(chosen.values()), include_property=False)
    view_by_property = {view.property_id: view for view in views}

    return [
        PropertyOut(
            id=prop.id,
            title=prop.title,
            description=prop.description,
            location=prop.location,
            area=prop.area,
            base_price=prop.base_price,
            image_url=prop.image_url,
            status=prop.status,
            created_by=prop.created_by,
            created_at=prop.created_at,
            updated_at=prop.updated_at,
            geometry=json.loads(geojson),
            wkt=wkt,
            centroid=(lat, lon),
            auction=view_by_property.get(prop.id),
        )
        for prop, geojson, wkt, lat, lon in rows
    ]


async def _area_sqft(db: AsyncSession, polygon: Polygon) -> Decimal:
    square_metres = await db.scalar(
        select(func.ST_Area(func.geography(func.ST_GeomFromText(polygon.wkt, SRID))))
    )
    area = (Decimal(str(square_metres or 0)) * SQFT_PER_SQM).quantize(Decimal("0.01"))
    if area <= 0:
        raise AppError("Polygon area is too small to be a land parcel.", "INVALID_POLYGON", 422)
    return area


async def list_properties(
    db: AsyncSession,
    *,
    bbox: tuple[float, float, float, float] | None,
    search: str | None,
    auction_statuses: list[AuctionStatus] | None,
    property_statuses: list[PropertyStatus] | None,
    limit: int,
    offset: int,
) -> list[PropertyOut]:
    stmt = _property_select()
    if property_statuses:
        stmt = stmt.where(Property.status.in_(property_statuses))
    else:
        stmt = stmt.where(Property.status != PropertyStatus.WITHDRAWN)
    if bbox:
        # Uses the GiST index on properties.geometry.
        stmt = stmt.where(func.ST_Intersects(Property.geometry, func.ST_MakeEnvelope(*bbox, SRID)))
    if search:
        pattern = f"%{_escape_like(search)}%"
        stmt = stmt.where(or_(Property.title.ilike(pattern, escape="\\"), Property.location.ilike(pattern, escape="\\")))
    if auction_statuses:
        stmt = stmt.where(
            exists().where(Auction.property_id == Property.id, Auction.status.in_(auction_statuses))
        )
    stmt = stmt.order_by(Property.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).all()
    return await _serialise(db, rows)


async def get_property(db: AsyncSession, property_id: int) -> PropertyOut:
    row = (await db.execute(_property_select().where(Property.id == property_id))).first()
    if row is None:
        raise AppError("Property does not exist.", "PROPERTY_NOT_FOUND", 404)
    return (await _serialise(db, [row]))[0]


async def create_property(db: AsyncSession, user: User, data: PropertyCreate) -> PropertyOut:
    polygon = parse_polygon_wkt(data.wkt)
    area = data.area if data.area is not None else await _area_sqft(db, polygon)

    prop = Property(
        title=data.title,
        description=data.description,
        location=data.location,
        area=area,
        base_price=data.base_price,
        image_url=data.image_url,
        geometry=WKTElement(polygon.wkt, srid=SRID),
        status=PropertyStatus.AVAILABLE,
        created_by=user.id,
    )
    db.add(prop)
    await db.flush()
    if data.auction is not None:
        await auction_service.schedule_auction(db, prop, data.auction)
    await db.commit()
    logger.info("Property %s created by user %s", prop.id, user.id)
    return await get_property(db, prop.id)


async def update_property(db: AsyncSession, user: User, property_id: int, data: PropertyUpdate) -> PropertyOut:
    prop = await db.scalar(select(Property).where(Property.id == property_id).with_for_update())
    if prop is None:
        raise AppError("Property does not exist.", "PROPERTY_NOT_FOUND", 404)
    ensure_can_manage_property(user, prop)

    changes = data.model_dump(exclude_unset=True)
    for field in ("title", "location", "base_price"):
        if field in changes and changes[field] is None:
            raise AppError(f"{field} cannot be null.", "VALIDATION_ERROR", 422)

    if "wkt" in changes or "base_price" in changes:
        live = await db.scalar(
            select(Auction.id).where(Auction.property_id == prop.id, Auction.status == AuctionStatus.LIVE).limit(1)
        )
        if live is not None or prop.status == PropertyStatus.SOLD:
            raise AppError(
                "Boundaries and base price cannot change while an auction is live or after the property is sold.",
                "PROPERTY_LOCKED",
                409,
            )

    wkt = changes.pop("wkt", None)
    if wkt is not None:
        polygon = parse_polygon_wkt(wkt)
        prop.geometry = WKTElement(polygon.wkt, srid=SRID)
        if "area" not in changes:
            prop.area = await _area_sqft(db, polygon)

    for field, value in changes.items():
        setattr(prop, field, value)
    await db.commit()
    return await get_property(db, prop.id)


async def delete_property(db: AsyncSession, user: User, property_id: int) -> None:
    prop = await db.scalar(select(Property).where(Property.id == property_id).with_for_update())
    if prop is None:
        raise AppError("Property does not exist.", "PROPERTY_NOT_FOUND", 404)
    ensure_can_manage_property(user, prop)

    has_bids = await db.scalar(
        select(exists().where(Bid.auction_id == Auction.id, Auction.property_id == property_id))
    )
    if has_bids:
        raise AppError(
            "This property has bidding history and cannot be deleted.", "PROPERTY_HAS_BIDS", 409
        )
    auction_rows = (
        await db.execute(select(Auction.id, Auction.status).where(Auction.property_id == property_id))
    ).all()
    if any(status == AuctionStatus.LIVE for _, status in auction_rows):
        raise AppError("Cannot delete a property with a live auction.", "AUCTION_LIVE", 409)

    await db.execute(delete(Property).where(Property.id == property_id))
    await db.commit()
    for auction_id, _ in auction_rows:
        try:
            await redis_service.delete_auction_state(auction_id)
        except RedisError:
            logger.warning("Could not clear Redis state for deleted auction %s", auction_id)
    logger.info("Property %s deleted by user %s", property_id, user.id)
