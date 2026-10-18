"""Initial schema: users, properties (PostGIS), auctions, immutable bid ledger.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-09-16
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

user_role = postgresql.ENUM("ADMIN", "SELLER", "BIDDER", name="user_role", create_type=False)
property_status = postgresql.ENUM(
    "AVAILABLE", "IN_AUCTION", "SOLD", "UNSOLD", "WITHDRAWN", name="property_status", create_type=False
)
auction_status = postgresql.ENUM("UPCOMING", "LIVE", "ENDED", "CANCELLED", name="auction_status", create_type=False)
bid_status = postgresql.ENUM("ACCEPTED", "REJECTED", name="bid_status", create_type=False)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    bind = op.get_bind()
    for enum in (user_role, property_status, auction_status, bid_status):
        enum.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("role", user_role, nullable=False, server_default="BIDDER"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.create_table(
        "properties",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("location", sa.String(255), nullable=False),
        sa.Column("area", sa.Numeric(18, 2), nullable=True),
        sa.Column("base_price", sa.Numeric(14, 2), nullable=False),
        sa.Column("image_url", sa.String(1024), nullable=True),
        sa.Column("status", property_status, nullable=False, server_default="AVAILABLE"),
        sa.Column("created_by", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_properties"),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_properties_created_by_users", ondelete="RESTRICT"
        ),
        sa.CheckConstraint("base_price > 0", name="ck_properties_base_price_positive"),
        sa.CheckConstraint("area IS NULL OR area > 0", name="ck_properties_area_positive"),
    )
    # Geometry column declared in SQL so the PostGIS type modifier and validity check are explicit.
    op.execute("ALTER TABLE properties ADD COLUMN geometry geometry(POLYGON, 4326) NOT NULL")
    op.execute(
        "ALTER TABLE properties ADD CONSTRAINT ck_properties_geometry_valid "
        "CHECK (ST_IsValid(geometry) AND NOT ST_IsEmpty(geometry))"
    )
    op.execute("CREATE INDEX idx_properties_geometry ON properties USING GIST (geometry)")
    op.create_index("ix_properties_status", "properties", ["status"])
    op.create_index("ix_properties_created_by", "properties", ["created_by"])

    op.create_table(
        "auctions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("property_id", sa.Integer(), nullable=False),
        sa.Column("starting_price", sa.Numeric(14, 2), nullable=False),
        sa.Column("current_price", sa.Numeric(14, 2), nullable=False),
        sa.Column("minimum_increment", sa.Numeric(14, 2), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", auction_status, nullable=False, server_default="UPCOMING"),
        sa.Column("winner_id", sa.Integer(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_auctions"),
        sa.ForeignKeyConstraint(
            ["property_id"], ["properties.id"], name="fk_auctions_property_id_properties", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["winner_id"], ["users.id"], name="fk_auctions_winner_id_users", ondelete="SET NULL"),
        sa.CheckConstraint("end_time > start_time", name="ck_auctions_time_window"),
        sa.CheckConstraint("starting_price > 0", name="ck_auctions_starting_price_positive"),
        sa.CheckConstraint("minimum_increment > 0", name="ck_auctions_increment_positive"),
        sa.CheckConstraint("current_price >= starting_price", name="ck_auctions_current_price_floor"),
    )
    op.create_index("ix_auctions_status_start_time", "auctions", ["status", "start_time"])
    op.create_index("ix_auctions_status_end_time", "auctions", ["status", "end_time"])
    op.create_index("ix_auctions_property_id", "auctions", ["property_id"])
    op.create_index(
        "uq_auctions_one_active_per_property",
        "auctions",
        ["property_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('UPCOMING', 'LIVE')"),
    )

    op.create_table(
        "bids",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("auction_id", sa.Integer(), nullable=False),
        sa.Column("bidder_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("bid_time", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("status", bid_status, nullable=False),
        sa.Column("rejection_reason", sa.String(64), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("sequence", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_bids"),
        sa.ForeignKeyConstraint(["auction_id"], ["auctions.id"], name="fk_bids_auction_id_auctions", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["bidder_id"], ["users.id"], name="fk_bids_bidder_id_users", ondelete="RESTRICT"),
        sa.CheckConstraint("amount > 0", name="ck_bids_amount_positive"),
    )
    op.create_index("ix_bids_auction_id_bid_time", "bids", ["auction_id", sa.text("bid_time DESC")])
    op.create_index("ix_bids_bidder_id", "bids", ["bidder_id"])
    op.create_index(
        "ix_bids_accepted_amount",
        "bids",
        ["auction_id", sa.text("amount DESC")],
        postgresql_where=sa.text("status = 'ACCEPTED'"),
    )

    # The bid ledger is append-only.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_bid_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'bids are immutable: % is not allowed', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER bids_immutable BEFORE UPDATE OR DELETE ON bids "
        "FOR EACH ROW EXECUTE FUNCTION prevent_bid_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS bids_immutable ON bids")
    op.execute("DROP FUNCTION IF EXISTS prevent_bid_mutation()")
    op.drop_table("bids")
    op.drop_table("auctions")
    op.drop_table("properties")
    op.drop_table("users")
    bind = op.get_bind()
    for enum in (bid_status, auction_status, property_status, user_role):
        enum.drop(bind, checkfirst=True)
