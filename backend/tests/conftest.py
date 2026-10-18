"""Test fixtures.

Integration tests run against real PostgreSQL/PostGIS and Redis (the concurrency
guarantees cannot be meaningfully tested with fakes). Configure them with
TEST_DATABASE_URL and TEST_REDIS_URL; tests that need them are skipped when the
services are unreachable. Pure unit tests always run.
"""

import os
import socket
import subprocess
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/landauction_test"
)
os.environ["REDIS_URL"] = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("JWT_SECRET", "test-only-secret-0123456789abcdefghijklmnopqrstuvwxyz")
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["RUN_BACKGROUND_TASKS"] = "false"
os.environ["DB_POOL_SIZE"] = "20"
os.environ["DB_MAX_OVERFLOW"] = "60"
os.environ["LOG_LEVEL"] = "WARNING"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from geoalchemy2 import WKTElement  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from pytest_asyncio import is_async_test  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.security import create_access_token, hash_password  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Auction, AuctionStatus, Property, PropertyStatus, User, UserRole  # noqa: E402
from app.services import auction_service  # noqa: E402
from app.services.redis_service import redis_service  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parent.parent
PASSWORD = "Passw0rd123"
_PASSWORD_HASH = hash_password(PASSWORD)
SAMPLE_WKT = "POLYGON((77.5946 12.9716, 77.5960 12.9716, 77.5960 12.9728, 77.5946 12.9728, 77.5946 12.9716))"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    session_loop = pytest.mark.asyncio(loop_scope="session")
    for item in items:
        if is_async_test(item):
            item.add_marker(session_loop, append=False)


def _reachable(url: str, default_port: int) -> bool:
    parsed = urlparse(url.replace("+asyncpg", ""))
    try:
        with socket.create_connection((parsed.hostname or "localhost", parsed.port or default_port), timeout=2):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def migrated_database() -> None:
    if not _reachable(os.environ["DATABASE_URL"], 5432):
        pytest.skip("PostgreSQL is not reachable (set TEST_DATABASE_URL)")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        pytest.fail(f"Alembic migration failed:\n{result.stdout}\n{result.stderr}")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def infrastructure(migrated_database: None):
    if not _reachable(os.environ["REDIS_URL"], 6379):
        pytest.skip("Redis is not reachable (set TEST_REDIS_URL)")
    await redis_service.connect(attempts=1)
    yield
    await redis_service.close()
    await engine.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def clean(infrastructure: None):
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE bids, auctions, properties, users RESTART IDENTITY CASCADE"))
    await redis_service.client.flushdb()
    yield


@pytest_asyncio.fixture(loop_scope="session")
async def db(clean: None):
    async with SessionLocal() as session:
        yield session


@pytest_asyncio.fixture(loop_scope="session")
async def client(clean: None):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


# ---------------------------------------------------------------------------- factories


async def create_user(role: UserRole = UserRole.BIDDER, name: str | None = None, email: str | None = None) -> User:
    async with SessionLocal() as session:
        count = (await session.execute(text("SELECT count(*) FROM users"))).scalar_one()
        user = User(
            name=name or f"{role.value.title()} {count + 1}",
            email=email or f"{role.value.lower()}{count + 1}-{os.urandom(3).hex()}@example.com",
            hashed_password=_PASSWORD_HASH,
            role=role,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def create_users(count: int, role: UserRole = UserRole.BIDDER) -> list[User]:
    async with SessionLocal() as session:
        suffix = os.urandom(3).hex()
        users = [
            User(name=f"Bidder {i}", email=f"bulk{i}-{suffix}@example.com", hashed_password=_PASSWORD_HASH, role=role)
            for i in range(count)
        ]
        session.add_all(users)
        await session.commit()  # primary keys are populated via INSERT ... RETURNING
        return users


def auth_headers(user: User) -> dict[str, str]:
    token, _ = create_access_token(user.id, user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def create_auction(
    seller: User,
    *,
    status: AuctionStatus = AuctionStatus.LIVE,
    starting_price: Decimal = Decimal("1000000"),
    increment: Decimal = Decimal("10000"),
    starts_in: timedelta = timedelta(minutes=-1),
    duration: timedelta = timedelta(hours=1),
) -> Auction:
    """Insert a property + auction directly (bypassing schedule validation) and return the auction."""
    now = auction_service.utcnow()
    async with SessionLocal() as session:
        prop = Property(
            title="Test Parcel",
            description="",
            location="Bengaluru",
            area=Decimal("2400"),
            base_price=starting_price,
            geometry=WKTElement(SAMPLE_WKT, srid=4326),
            status=PropertyStatus.IN_AUCTION,
            created_by=seller.id,
        )
        session.add(prop)
        await session.flush()
        auction = Auction(
            property_id=prop.id,
            starting_price=starting_price,
            current_price=starting_price,
            minimum_increment=increment,
            start_time=now + starts_in,
            end_time=now + starts_in + duration,
            status=status,
        )
        session.add(auction)
        await session.commit()
        auction_id = auction.id
    async with SessionLocal() as session:
        await auction_service.ensure_loaded(session, auction_id)
        return await auction_service.get_auction(session, auction_id)
