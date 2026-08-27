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
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

# Create the async engine — this is the connection pool to PostgreSQL
# echo=True logs all SQL queries (useful for debugging, disable in production)
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=5,          # Keep 5 connections ready
    max_overflow=10,      # Allow up to 10 more under load
)

# Session factory — creates new database sessions
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Don't expire objects after commit
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
