"""
Database Connection — SQLAlchemy Async Engine + Session
=======================================================

This file creates the database connection that all other files use.

Flow:
    FastAPI endpoint
        ↓
    Depends(get_db)          ← injects a database session
        ↓
    AsyncSession             ← this file creates these
        ↓
    SQLAlchemy executes SQL
        ↓
    PostgreSQL
"""
import ssl as ssl_module
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


def _fix_database_url(url: str) -> dict:
    """
    Fix DATABASE_URL for asyncpg compatibility.
    
    Neon/Supabase URLs include ?sslmode=require, but asyncpg
    doesn't accept 'sslmode' as a query param. We need to:
    1. Strip sslmode from the URL
    2. Pass ssl=True as a connect_arg instead
    """
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)
    
    needs_ssl = False
    if "sslmode" in query_params:
        needs_ssl = query_params["sslmode"][0] in ("require", "verify-full", "verify-ca")
        del query_params["sslmode"]
    
    # Rebuild URL without sslmode
    clean_query = urlencode(query_params, doseq=True)
    clean_url = urlunparse(parsed._replace(query=clean_query))
    
    connect_args = {}
    if needs_ssl:
        connect_args["ssl"] = True
    
    return {"url": clean_url, "connect_args": connect_args}


db_config = _fix_database_url(settings.DATABASE_URL)

# Create the async engine — this is the connection pool to PostgreSQL
engine = create_async_engine(
    db_config["url"],
    echo=settings.DEBUG,
    pool_size=3,
    max_overflow=5,
    connect_args=db_config["connect_args"],
)

# Session factory — creates new database sessions
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# Base class for all database models
class Base(DeclarativeBase):
    pass


async def get_db():
    """
    Dependency that provides a database session to endpoints.
    
    Usage in endpoints:
        @router.get("/jobs")
        async def list_jobs(db: AsyncSession = Depends(get_db)):
            ...
    
    The `async with` ensures the session is properly closed
    even if an error occurs.
    """
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Create all tables. Used for development — in production use Alembic migrations."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
