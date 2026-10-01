"""UTC time helpers that behave the same on PostgreSQL (aware) and SQLite (naive)."""
from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: datetime | None) -> datetime | None:
    """Normalize a datetime read from the DB to an aware UTC datetime.

    SQLite returns naive datetimes; every timestamp we write is UTC, so a naive
    value is interpreted as UTC.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    dt = as_utc(dt)
    return dt.isoformat() if dt else None
