"""Management commands.

    python -m app.cli create-admin --email admin@example.com --name "Admin" --password "S3cure-pass"
    python -m app.cli seed-demo
"""

import argparse
import asyncio
import getpass
import sys
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from app.core.security import hash_password
from app.database import SessionLocal, engine
from app.models import User, UserRole
from app.schemas.auction import AuctionSchedule
from app.schemas.property import PropertyCreate
from app.services import auction_service, property_service
from app.services.redis_service import redis_service


async def _get_or_create_user(email: str, name: str, password: str, role: UserRole) -> User:
    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == email.lower()))
        if user is None:
            user = User(name=name, email=email.lower(), hashed_password=hash_password(password), role=role)
            db.add(user)
            await db.commit()
            await db.refresh(user)
            print(f"Created {role.value} {email}")
        else:
            print(f"User {email} already exists ({user.role.value})")
        return user


async def create_admin(email: str, name: str, password: str | None) -> None:
    if not password:
        password = getpass.getpass("Admin password: ")
    if len(password) < 8:
        sys.exit("Password must be at least 8 characters.")
    user = await _get_or_create_user(email, name, password, UserRole.ADMIN)
    if user.role != UserRole.ADMIN:
        async with SessionLocal() as db:
            db_user = await db.get(User, user.id)
            db_user.role = UserRole.ADMIN
            await db.commit()
        print(f"Promoted {email} to ADMIN")


def _parcel(lon: float, lat: float, width: float, height: float, skew: float = 0.0) -> str:
    points = [
        (lon, lat),
        (lon + width, lat + skew),
        (lon + width + skew, lat + height),
        (lon - skew, lat + height - skew),
        (lon, lat),
    ]
    return "POLYGON((" + ", ".join(f"{x:.6f} {y:.6f}" for x, y in points) + "))"


DEMO_PARCELS = [
    ("Green Valley Plot", "Whitefield, Bengaluru", 77.7480, 12.9698, "2500000", "50000", 0, 45),
    ("Lakeview Residential Parcel", "Hebbal, Bengaluru", 77.5920, 13.0358, "8200000", "100000", 0, 30),
    ("Tech Corridor Commercial Land", "Electronic City, Bengaluru", 77.6690, 12.8452, "15500000", "250000", 20, 120),
    ("Nandi Hills Farm Estate", "Nandi Hills, Chikkaballapur", 77.6835, 13.3702, "4600000", "75000", 90, 24 * 60),
    ("Sarjapur Villa Plot", "Sarjapur Road, Bengaluru", 77.6870, 12.9010, "6100000", "100000", 0, 90),
]


async def seed_demo() -> None:
    await redis_service.connect()
    try:
        seller = await _get_or_create_user("seller@terrabid.dev", "Demo Seller", "Seller12345", UserRole.SELLER)
        for i in range(1, 4):
            await _get_or_create_user(f"bidder{i}@terrabid.dev", f"Bidder {i}", "Bidder12345", UserRole.BIDDER)

        now = auction_service.utcnow()
        for title, location, lon, lat, price, increment, starts_in, duration in DEMO_PARCELS:
            payload = PropertyCreate(
                title=title,
                description=f"Clear-title land parcel in {location}. Road access, surveyed boundaries.",
                location=location,
                base_price=Decimal(price),
                wkt=_parcel(lon, lat, 0.0016, 0.0011, 0.00015),
                auction=AuctionSchedule(
                    start_time=now + timedelta(minutes=starts_in),
                    end_time=now + timedelta(minutes=starts_in + duration),
                    minimum_increment=Decimal(increment),
                ),
            )
            async with SessionLocal() as db:
                created = await property_service.create_property(db, seller, payload)
            print(f"Created property #{created.id}: {title} (auction starts in {starts_in} min)")
        print("\nDemo accounts: seller@terrabid.dev / Seller12345, bidder1..3@terrabid.dev / Bidder12345")
    finally:
        await redis_service.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    admin = sub.add_parser("create-admin", help="Create (or promote) an administrator")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", default="Administrator")
    admin.add_argument("--password", help="Omit to be prompted securely")

    sub.add_parser("seed-demo", help="Create demo users, properties and auctions")

    args = parser.parse_args()

    async def run() -> None:
        try:
            if args.command == "create-admin":
                await create_admin(args.email, args.name, args.password)
            elif args.command == "seed-demo":
                await seed_demo()
        finally:
            await engine.dispose()

    asyncio.run(run())


if __name__ == "__main__":
    main()
