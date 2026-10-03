"""
Auth Service — Business Logic for Authentication
=================================================

Separates business logic from the API route handlers.

Route handler (auth.py) → Service (this file) → Database

Why separate?
- Routes handle HTTP (request/response)
- Services handle business logic (hashing, token creation, validation)
- This makes testing easier — you can test business logic without HTTP
"""
import asyncio
import functools
import secrets
from datetime import datetime, timedelta, timezone

import dns.resolver
from jose import JWTError, jwt
import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import User


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except (ValueError, TypeError):
        # Malformed stored hash — treat as a failed login rather than a 500.
        return False


def create_access_token(data: dict, expires_minutes: int = None) -> str:
    """Sign a JWT. Callers pass ``tv`` (the user's token version) so that a
    password reset, which bumps the version, invalidates older tokens."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "iat": now})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm="HS256")


def decode_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        return payload
    except JWTError:
        return None


# ---------------------------------------------------------------------------
# Email-domain validation
# ---------------------------------------------------------------------------
def _domain_deliverable_sync(domain: str) -> bool:
    """
    Return True if `domain` can plausibly receive email.

    Policy:
    - MX records present            -> deliverable (True)
    - No MX but A/AAAA present      -> deliverable per RFC 5321 fallback (True)
    - Domain does not exist (NXDOMAIN) -> reject (False)
    - Resolver timeout / no nameservers / other infra error -> FAIL OPEN (True)

    Failing open on infra errors means a transient DNS problem never blocks a
    legitimate signup; we only reject domains we can positively prove are fake.
    """
    if not domain or "." not in domain:
        return False

    resolver = dns.resolver.Resolver()
    resolver.timeout = 5.0
    resolver.lifetime = 5.0

    try:
        answers = resolver.resolve(domain, "MX")
        return len(answers) > 0
    except dns.resolver.NoAnswer:
        for rtype in ("A", "AAAA"):
            try:
                if resolver.resolve(domain, rtype):
                    return True
            except Exception:
                continue
        return False
    except dns.resolver.NXDOMAIN:
        return False
    except Exception:
        # Timeout, NoNameservers, network error, etc. — don't punish the user.
        return True


async def email_domain_deliverable(domain: str) -> bool:
    """Async wrapper: run the blocking DNS lookup off the event loop."""
    return await asyncio.to_thread(_domain_deliverable_sync, domain)


# ---------------------------------------------------------------------------
# User queries
# ---------------------------------------------------------------------------
async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    """Exact match, else an unambiguous case-insensitive match (new accounts are
    stored lower-case; older ones keep the casing they were registered with)."""
    from app.services.email_auth import find_user

    return await find_user(db, email)


async def get_user_by_id(db: AsyncSession, user_id: int) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def create_user(db: AsyncSession, email: str, password: str, full_name: str) -> User:
    user = User(
        email=email,
        full_name=full_name,
        hashed_password=hash_password(password),
    )
    db.add(user)
    await db.flush()  # Get the ID without committing
    await db.refresh(user)
    return user


@functools.lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    """A real bcrypt hash (same cost as user hashes) of a random throwaway value."""
    return hash_password(secrets.token_urlsafe(32))


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User | None:
    user = await get_user_by_email(db, email)
    if not user:
        # Spend the same bcrypt work as a real check, so response time does not
        # reveal whether an account exists.
        verify_password(password, _dummy_password_hash())
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


async def authenticate_with_snapshot(db: AsyncSession, email: str, password: str):
    """Like authenticate_user, but checks the password against a hash read in
    the SAME statement as the token version / verification state, and returns
    ``(user, AuthSnapshot)``. A password reset that commits mid-login can then
    never yield a session for the old password with the new token version."""
    from app.services.email_auth import snapshot

    user = await get_user_by_email(db, email)
    if not user:
        verify_password(password, _dummy_password_hash())
        return None
    found = await snapshot(db, user.id)
    if found is None:
        verify_password(password, _dummy_password_hash())
        return None
    hashed, snap = found
    if not verify_password(password, hashed):
        return None
    return user, snap
