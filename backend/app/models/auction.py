from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, Numeric, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import AuctionStatus
from app.models.mixins import TimestampMixin
from app.models.property import Property


class Auction(TimestampMixin, Base):
    __tablename__ = "auctions"
    __table_args__ = (
        CheckConstraint("end_time > start_time", name="time_window"),
        CheckConstraint("starting_price > 0", name="starting_price_positive"),
        CheckConstraint("minimum_increment > 0", name="increment_positive"),
        CheckConstraint("current_price >= starting_price", name="current_price_floor"),
        Index("ix_auctions_status_start_time", "status", "start_time"),
        Index("ix_auctions_status_end_time", "status", "end_time"),
        Index("ix_auctions_property_id", "property_id"),
        # A property can have at most one auction that is scheduled or running.
        Index(
            "uq_auctions_one_active_per_property",
            "property_id",
            unique=True,
            postgresql_where=text("status IN ('UPCOMING', 'LIVE')"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    starting_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    current_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    minimum_increment: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[AuctionStatus] = mapped_column(
        Enum(AuctionStatus, name="auction_status"), nullable=False, default=AuctionStatus.UPCOMING
    )
    winner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    property: Mapped[Property] = relationship(lazy="joined", innerjoin=True)
