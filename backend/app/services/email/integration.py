"""
Email integration lifecycle: status, connect, test, disconnect.
===============================================================

Two separate authentication systems — never mixed:
  * Career Platform auth: email/password → JWT (handled in app/api/auth.py).
  * Mailbox auth: the platform user's stored, encrypted IMAP credential.
Mailbox credentials are never used to authenticate to the platform, and mailbox
failures never produce a 401.

Credential rotation: new credentials are verified BEFORE anything is written,
so a failed reconnect can never overwrite a working credential.
"""
import asyncio
import logging

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.encryption import CredentialDecryptionError, decrypt_credentials, encrypt_credentials
from app.core.rate_limit import SlidingWindowLimiter
from app.core.timeutil import iso, utcnow
from app.models import EmailIntegration, EmailMessage, JobSuggestion, User
from app.services.email.ai_extractor import ai_enabled
from app.services.email.errors import (
    AuthenticationFailed, EmailProviderError, HostResolutionError, InvalidAccountDetails, UnsafeHostError,
)
from app.services.email.providers import PROVIDERS, EmailProvider, get_provider
from app.services.email.sync import KEY_CHANGED_MESSAGE, cooldown_remaining, sync_in_progress

logger = logging.getLogger("app.email")

connect_limiter = SlidingWindowLimiter(settings.EMAIL_CONNECT_MAX_ATTEMPTS, settings.EMAIL_RATE_WINDOW_SECONDS)
test_limiter = SlidingWindowLimiter(settings.EMAIL_TEST_MAX_ATTEMPTS, settings.EMAIL_RATE_WINDOW_SECONDS)


class RateLimited(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__("rate limited")


class NotConnected(Exception):
    pass


async def get_active_integration(db: AsyncSession, user_id: int) -> EmailIntegration | None:
    return (await db.execute(
        select(EmailIntegration)
        .where(EmailIntegration.user_id == user_id, EmailIntegration.is_active.is_(True))
        .order_by(EmailIntegration.updated_at.desc(), EmailIntegration.id.desc())
        .limit(1)
    )).scalar_one_or_none()


async def has_active_integration(db: AsyncSession, user_id: int) -> bool:
    return (await get_active_integration(db, user_id)) is not None


def _deactivate(integ: EmailIntegration) -> None:
    integ.is_active = False
    integ.encrypted_credentials = None      # revoke: ciphertext is destroyed, not just hidden
    integ.status = "disconnected"
    integ.status_detail = None
    integ.sync_lock_until = None
    integ.updated_at = utcnow()


def _clear_legacy(user: User) -> None:
    """Wipe superseded pre-integration credentials from the users table."""
    if user.email_user or user.email_app_password or user.email_host:
        user.email_user = None
        user.email_app_password = None
        user.email_host = None


async def _verify(provider: EmailProvider, account) -> None:
    await asyncio.to_thread(
        provider.verify, account, settings.EMAIL_IMAP_TIMEOUT_SECONDS, settings.EMAIL_SYNC_MAILBOX
    )


# ---------------------------------------------------------------------------
# Connect
# ---------------------------------------------------------------------------
async def connect(
    db: AsyncSession, user: User, *, provider_id: str, email: str, password: str, host: str | None
) -> EmailIntegration:
    retry = connect_limiter.hit(user.id)
    if retry:
        raise RateLimited(retry)

    provider = get_provider(provider_id)
    account = provider.build_account(email=email, password=password, host=host)

    # Verify first. Any failure raises here, before the DB is touched.
    await _verify(provider, account)

    now = utcnow()
    token = encrypt_credentials({"password": account.password}, user_id=user.id, account=account.username)

    rows = (await db.execute(
        select(EmailIntegration).where(EmailIntegration.user_id == user.id)
    )).scalars().all()
    target = next((r for r in rows if r.email_address == account.username), None)
    for other in rows:
        if other is not target and other.is_active:
            _deactivate(other)           # one active mailbox per user (for now)

    if target is None:
        target = EmailIntegration(user_id=user.id, email_address=account.username)
        db.add(target)
    was_active = bool(target.is_active and target.encrypted_credentials)

    target.provider = provider.id
    target.host = account.host
    target.port = account.port
    target.encrypted_credentials = token
    target.is_active = True
    target.status = "connected"
    target.status_detail = None
    target.last_verified_at = now
    target.sync_lock_until = None
    if not was_active:
        target.connected_at = now
    target.updated_at = now
    _clear_legacy(user)
    await db.flush()
    logger.info("email.connect.ok user_id=%s integration_id=%s provider=%s", user.id, target.id, provider.id)
    return target


# ---------------------------------------------------------------------------
# Test stored connection
# ---------------------------------------------------------------------------
async def test_connection(db: AsyncSession, user: User) -> tuple[bool, str, str | None]:
    """Returns (ok, user_message, error_code)."""
    integ = await get_active_integration(db, user.id)
    if integ is None:
        raise NotConnected()
    retry = test_limiter.hit(user.id)
    if retry:
        raise RateLimited(retry)

    provider = get_provider(integ.provider)
    try:
        secret = decrypt_credentials(integ.encrypted_credentials, user_id=user.id, account=integ.email_address)
        account = provider.build_account(
            email=integ.email_address, password=secret.get("password", ""),
            host=None if provider.fixed_host else integ.host,
        )
    except (CredentialDecryptionError, InvalidAccountDetails):
        integ.status, integ.status_detail = "needs_reconnect", KEY_CHANGED_MESSAGE
        return False, KEY_CHANGED_MESSAGE, "reconnect_required"
    finally:
        secret = None  # noqa: F841

    try:
        await _verify(provider, account)
    except (AuthenticationFailed, UnsafeHostError) as exc:
        integ.status, integ.status_detail = "needs_reconnect", exc.user_message[:255]
        return False, exc.user_message, exc.code
    except (HostResolutionError, EmailProviderError) as exc:
        # Transient: keep the connection marked usable, just report the problem.
        return False, exc.user_message, exc.code

    integ.status, integ.status_detail = "connected", None
    integ.last_verified_at = utcnow()
    return True, "Connection verified. Your mailbox is reachable.", None


# ---------------------------------------------------------------------------
# Disconnect
# ---------------------------------------------------------------------------
async def disconnect(db: AsyncSession, user: User, *, delete_imported_emails: bool = False) -> None:
    rows = (await db.execute(
        select(EmailIntegration).where(EmailIntegration.user_id == user.id, EmailIntegration.is_active.is_(True))
    )).scalars().all()
    for integ in rows:
        _deactivate(integ)
    _clear_legacy(user)
    if delete_imported_emails:
        # Jobs are never deleted here — only imported email data and suggestions.
        await db.execute(delete(JobSuggestion).where(JobSuggestion.user_id == user.id))
        await db.execute(delete(EmailMessage).where(EmailMessage.user_id == user.id))
    await db.flush()
    logger.info("email.disconnect user_id=%s integrations=%s purge=%s", user.id, len(rows), delete_imported_emails)


# ---------------------------------------------------------------------------
# Status (never includes credentials)
# ---------------------------------------------------------------------------
async def build_status(db: AsyncSession, user: User) -> dict:
    integ = await get_active_integration(db, user.id)
    pending = (await db.execute(
        select(func.count(JobSuggestion.id)).where(
            JobSuggestion.user_id == user.id, JobSuggestion.review_status == "pending"
        )
    )).scalar() or 0

    base = {
        "pending_suggestions": int(pending),
        "ai_enabled": ai_enabled(),
        "providers": [p.public_info() for p in PROVIDERS.values()],
        "limits": {
            "default_days": settings.EMAIL_SYNC_DEFAULT_DAYS,
            "max_days": settings.EMAIL_SYNC_MAX_DAYS,
            "default_messages": settings.EMAIL_SYNC_DEFAULT_MESSAGES,
            "max_messages": settings.EMAIL_SYNC_MAX_MESSAGES,
            "cooldown_seconds": settings.EMAIL_SYNC_COOLDOWN_SECONDS,
        },
    }
    if integ is None:
        legacy = user.has_legacy_email_credentials
        return {
            **base,
            "state": "legacy_reconnect" if legacy else "not_connected",
            "connected": False,
            "provider": None, "provider_name": None, "email": None, "host": None,
            "status_detail": (
                "Email sync was rebuilt. Reconnect your mailbox to start using it." if legacy else None
            ),
            "connected_at": None, "last_verified_at": None, "sync": None,
        }

    provider = PROVIDERS.get(integ.provider)
    now = utcnow()
    healthy = integ.status == "connected"
    return {
        **base,
        "state": "connected" if healthy else "needs_attention",
        "connected": healthy,
        "provider": integ.provider,
        "provider_name": provider.name if provider else integ.provider,
        "email": integ.email_address,
        "host": integ.host,
        "status_detail": integ.status_detail,
        "connected_at": iso(integ.connected_at),
        "last_verified_at": iso(integ.last_verified_at),
        "sync": {
            "in_progress": sync_in_progress(integ, now),
            "last_sync_at": iso(integ.last_sync_at),
            "last_status": integ.last_sync_status,
            "last_error": integ.last_sync_error,
            "last_scanned": integ.last_sync_scanned,
            "last_new_messages": integ.last_sync_new_messages,
            "last_job_related": integ.last_sync_job_related,
            "last_new_suggestions": integ.last_sync_new_suggestions,
            "cooldown_seconds_remaining": cooldown_remaining(integ, now),
        },
    }
