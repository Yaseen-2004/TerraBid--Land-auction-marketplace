from decimal import Decimal

from geoalchemy2 import Geometry, WKBElement
from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.enums import PropertyStatus
from app.models.mixins import TimestampMixin


class Property(TimestampMixin, Base):
    __tablename__ = "properties"
    __table_args__ = (
        CheckConstraint("base_price > 0", name="base_price_positive"),
        CheckConstraint("area IS NULL OR area > 0", name="area_positive"),
        Index("idx_properties_geometry", "geometry", postgresql_using="gist"),
        Index("ix_properties_status", "status"),
        Index("ix_properties_created_by", "created_by"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    location: Mapped[str] = mapped_column(String(255), nullable=False)
    # Area in square feet. Computed from the polygon when not supplied.
    area: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    base_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(1024))
    geometry: Mapped[WKBElement] = mapped_column(
        Geometry(geometry_type="POLYGON", srid=4326, spatial_index=False), nullable=False
    )
    status: Mapped[PropertyStatus] = mapped_column(
        Enum(PropertyStatus, name="property_status"), nullable=False, default=PropertyStatus.AVAILABLE
    )
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
