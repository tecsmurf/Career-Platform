"""
Shared pytest fixtures.

- A SQLite test database, recreated for every test.
- `client` / `auth_client` HTTP clients, plus `make_client` for multi-user tests.
- Registration performs a real DNS/MX lookup to reject fake email domains; unit
  tests must not depend on live DNS, so the domain check is stubbed to accept
  any domain (individual tests can override it).
- Email-integration safety nets: rate limiters reset between tests and the
  sync cooldown defaults to 0 (tests that exercise throttling set it).
- Login rate limiter: fresh in-process buckets for every test.
- bcrypt runs at cost 4 (same code path, much faster).
"""
import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.database.connection import Base, get_db
from app.main import app
from app.services import auth_service

# SQLite by default; set TEST_DATABASE_URL to run the suite against PostgreSQL, e.g.
#   TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/career_test
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite:///./test.db")

# Mirror production: bound parameters never appear in SQL logs or exceptions.
# NullPool: each test runs on its own event loop, and asyncpg connections are
# bound to the loop that created them, so connections must not be reused.
test_engine = create_async_engine(TEST_DATABASE_URL, echo=False, hide_parameters=True, poolclass=NullPool)
test_session = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


async def override_get_db():
    async with test_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def _accept_all_email_domains(monkeypatch):
    async def _ok(domain: str) -> bool:
        return True

    monkeypatch.setattr(auth_service, "email_domain_deliverable", _ok)


@pytest.fixture(autouse=True)
def _email_test_defaults(monkeypatch):
    from app.services.email import integration

    monkeypatch.setattr(settings, "EMAIL_SYNC_COOLDOWN_SECONDS", 0)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    integration.connect_limiter.reset()
    integration.test_limiter.reset()
    yield
    integration.connect_limiter.reset()
    integration.test_limiter.reset()


@pytest.fixture(autouse=True)
def _fresh_login_limiter():
    """Every test starts with empty, in-process login buckets (real clock)."""
    from app.core.token_bucket import MemoryTokenBuckets
    from app.services.login_limiter import login_limiter

    login_limiter.use_store(MemoryTokenBuckets())
    yield
    login_limiter.use_store(MemoryTokenBuckets())


@pytest.fixture(autouse=True)
def _fast_bcrypt(monkeypatch):
    """bcrypt at cost 4 instead of 12 for tests: identical code path, ~100x faster
    (the rate-limiter tests make hundreds of logins). Production cost is unchanged."""
    real_gensalt = auth_service.bcrypt.gensalt
    monkeypatch.setattr(auth_service.bcrypt, "gensalt", lambda rounds=12, prefix=b"2b": real_gensalt(4, prefix))
    auth_service._dummy_password_hash.cache_clear()
    yield
    auth_service._dummy_password_hash.cache_clear()


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Create tables before each test, drop after."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session():
    async with test_session() as session:
        yield session


@pytest_asyncio.fixture
async def client():
    """HTTP test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def auth_client(client: AsyncClient):
    """Authenticated test client — registers a user and sets the token."""
    res = await client.post("/api/auth/register", json={
        "email": "test@example.com",
        "password": "testpass123",
        "full_name": "Test User",
    })
    token = res.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


@pytest_asyncio.fixture
async def make_client():
    """Factory: independent authenticated clients for multi-user tests."""
    clients = []

    async def _make(email: str, password: str = "testpass123", name: str = "User") -> AsyncClient:
        ac = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        clients.append(ac)
        res = await ac.post("/api/auth/register", json={"email": email, "password": password, "full_name": name})
        assert res.status_code == 201, res.text
        ac.headers["Authorization"] = f"Bearer {res.json()['access_token']}"
        return ac

    yield _make
    for ac in clients:
        await ac.aclose()
