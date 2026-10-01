"""
Email sync engine — bounded, idempotent, never blocks the event loop.
=====================================================================

    claim (atomic UPDATE: not locked, cooldown elapsed, status connected)
      → decrypt credentials in memory
      → connect (SSRF-pinned, verified TLS, timeouts) → EXAMINE mailbox (read-only)
      → UID SEARCH SINCE <window>  → newest N UIDs
      → fetch HEADERS only → dedup against stored (user_id, message_key)
      → pre-filter on headers → fetch body (first 128 KB, BODY.PEEK) only for candidates
      → parse → classify (rules [+ AI]) → store → create/merge suggestion
      → update sync metadata → release lock → logout

Guarantees:
- Idempotent: a message is stored at most once per user (unique constraint +
  pre-check); re-running sync never duplicates emails or suggestions.
- Data minimisation: non-job emails are stored as a bare dedup key (no sender,
  subject or body). Bodies of non-candidates are never downloaded.
- Never modifies jobs. It only produces suggestions for the user to review.
- Every blocking IMAP call runs in a worker thread; a total time budget stops
  the sync cleanly (status "partial") instead of hanging.
- The DB transaction is never held open across network I/O.
- The lock is always released, including on unexpected errors.
"""
import asyncio
import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.encryption import CredentialDecryptionError, decrypt_credentials
from app.core.timeutil import as_utc, utcnow
from app.models import EmailIntegration, EmailMessage
from app.services.email.ai_extractor import ai_classify, ai_enabled, merge
from app.services.email.classifier import classify, prefilter
from app.services.email.errors import (
    AuthenticationFailed, EmailProviderError, InvalidAccountDetails, MailboxError, UnsafeHostError,
)
from app.services.email.imap_client import since_date
from app.services.email.parsing import effective_received_at, message_key, parse_headers, parse_message
from app.services.email.providers import get_provider
from app.services.email.suggestions import record_suggestion

logger = logging.getLogger("app.email.sync")

KEY_CHANGED_MESSAGE = (
    "Your saved email credentials can no longer be read (the server's encryption key "
    "changed). Reconnect your email to continue."
)
PARTIAL_MESSAGE = "Some messages couldn't be synced this time. Run sync again to continue."
TIME_LIMIT_MESSAGE = "Sync stopped at the time limit. Run it again to continue where it left off."


class SyncBlocked(Exception):
    def __init__(self, code: str, message: str, http_status: int, retry_after: int | None = None):
        self.code, self.message, self.http_status, self.retry_after = code, message, http_status, retry_after
        super().__init__(message)


class SyncFailed(Exception):
    def __init__(self, code: str, message: str, http_status: int):
        self.code, self.message, self.http_status = code, message, http_status
        super().__init__(message)


@dataclass
class SyncSummary:
    status: str = "success"          # success | partial
    scanned: int = 0                 # messages in the window we looked at
    new_messages: int = 0            # newly stored
    skipped_duplicates: int = 0      # already synced before
    job_related: int = 0
    new_suggestions: int = 0
    updated_suggestions: int = 0
    errors: int = 0
    ai_used: int = 0
    message: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Claim / release
# ---------------------------------------------------------------------------
def cooldown_remaining(integ: EmailIntegration, now: datetime | None = None) -> int:
    now = now or utcnow()
    started = as_utc(integ.last_sync_started_at)
    if not started:
        return 0
    remaining = settings.EMAIL_SYNC_COOLDOWN_SECONDS - (now - started).total_seconds()
    return max(0, int(remaining + 0.999))


def sync_in_progress(integ: EmailIntegration, now: datetime | None = None) -> bool:
    lock = as_utc(integ.sync_lock_until)
    return bool(lock and lock > (now or utcnow()))


async def claim_sync(db: AsyncSession, integ: EmailIntegration) -> None:
    """Atomically take the per-integration sync lock (safe across processes)."""
    now = utcnow()
    res = await db.execute(
        update(EmailIntegration)
        .where(
            EmailIntegration.id == integ.id,
            EmailIntegration.user_id == integ.user_id,
            EmailIntegration.is_active.is_(True),
            EmailIntegration.status == "connected",
            or_(EmailIntegration.sync_lock_until.is_(None), EmailIntegration.sync_lock_until < now),
            or_(
                EmailIntegration.last_sync_started_at.is_(None),
                EmailIntegration.last_sync_started_at <= now - timedelta(seconds=settings.EMAIL_SYNC_COOLDOWN_SECONDS),
            ),
        )
        .values(
            sync_lock_until=now + timedelta(seconds=settings.EMAIL_SYNC_LOCK_SECONDS),
            last_sync_started_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    claimed = res.rowcount == 1
    await db.commit()
    await db.refresh(integ)
    if claimed:
        return
    if not integ.is_active:
        raise SyncBlocked("not_connected", "Connect your email first.", 409)
    if integ.status != "connected":
        raise SyncBlocked(
            "reconnect_required",
            integ.status_detail or "Your email connection needs attention. Reconnect to continue.",
            409,
        )
    if sync_in_progress(integ):
        raise SyncBlocked("sync_in_progress", "A sync is already running for this mailbox.", 409)
    wait = cooldown_remaining(integ)
    if wait <= 0:
        # The claim lost to a sync that held the lock and has finished since
        # (re-read above). Not a cooldown — don't invent a wait time.
        raise SyncBlocked("sync_in_progress", "A sync for this mailbox just finished. Refresh to see the results.", 409)
    raise SyncBlocked("cooldown", f"Please wait {wait} seconds before syncing again.", 429, retry_after=wait)


async def _record_failure(db: AsyncSession, integ: EmailIntegration, message: str, *, needs_reconnect: bool) -> None:
    await db.rollback()
    await db.refresh(integ)
    integ.sync_lock_until = None
    integ.last_sync_status = "failed"
    integ.last_sync_error = message[:255]
    if needs_reconnect:
        integ.status = "needs_reconnect"
        integ.status_detail = message[:255]
    await db.commit()


async def _release_lock_after_crash(db: AsyncSession, integ_id: int, user_id: int) -> None:
    try:
        await db.rollback()
        await db.execute(
            update(EmailIntegration)
            .where(EmailIntegration.id == integ_id, EmailIntegration.user_id == user_id)
            .values(sync_lock_until=None, last_sync_status="failed",
                    last_sync_error="Sync failed unexpectedly. Please try again.")
            .execution_options(synchronize_session=False)
        )
        await db.commit()
    except Exception:
        logger.exception("email.sync.lock_release_failed integration_id=%s", integ_id)


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------
async def run_sync(
    db: AsyncSession,
    user_id: int,
    integ: EmailIntegration,
    *,
    days_back: int,
    max_messages: int,
    ai_client=None,
) -> SyncSummary:
    """Run one sync. Caller must have called claim_sync() first."""
    integ_id = integ.id
    try:
        return await _run_sync(db, user_id, integ, days_back=days_back, max_messages=max_messages, ai_client=ai_client)
    except (SyncFailed, SyncBlocked):
        raise
    except Exception:
        logger.exception("email.sync.crashed user_id=%s integration_id=%s", user_id, integ_id)
        await _release_lock_after_crash(db, integ_id, user_id)
        raise SyncFailed("sync_error", "Email sync failed unexpectedly. Please try again.", 500)


async def _close(session) -> None:
    if session is not None:
        try:
            await asyncio.to_thread(session.close)
        except Exception:
            pass


async def _run_sync(db, user_id, integ, *, days_back, max_messages, ai_client) -> SyncSummary:
    provider = get_provider(integ.provider)
    mailbox = settings.EMAIL_SYNC_MAILBOX
    timeout = settings.EMAIL_IMAP_TIMEOUT_SECONDS

    # 1. Credentials (decrypted only in memory, only for this call).
    try:
        secret = decrypt_credentials(integ.encrypted_credentials, user_id=user_id, account=integ.email_address)
        account = provider.build_account(
            email=integ.email_address,
            password=secret.get("password", ""),
            host=None if provider.fixed_host else integ.host,
        )
    except (CredentialDecryptionError, InvalidAccountDetails):
        await _record_failure(db, integ, KEY_CHANGED_MESSAGE, needs_reconnect=True)
        raise SyncFailed("reconnect_required", KEY_CHANGED_MESSAGE, 409)
    finally:
        secret = None  # noqa: F841 — drop our reference to the plaintext promptly

    deadline = time.monotonic() + settings.EMAIL_SYNC_TIME_BUDGET_SECONDS
    summary = SyncSummary()
    session = None

    # 2. Connect + list + headers.
    try:
        session = await asyncio.to_thread(provider.open, account, timeout)
        account = None
        uidvalidity = await asyncio.to_thread(session.select_readonly, mailbox)
        uids = await asyncio.to_thread(session.search_uids_since, since_date(days_back))
        uids = uids[-max_messages:]
        headers = await asyncio.to_thread(session.fetch_headers, uids)
    except (AuthenticationFailed, UnsafeHostError) as exc:
        await _close(session)
        await _record_failure(db, integ, exc.user_message, needs_reconnect=True)
        logger.info("email.sync.failed user_id=%s integration_id=%s code=%s", user_id, integ.id, exc.code)
        raise SyncFailed(exc.code, exc.user_message, exc.http_status)
    except EmailProviderError as exc:
        await _close(session)
        await _record_failure(db, integ, exc.user_message, needs_reconnect=False)
        logger.info("email.sync.failed user_id=%s integration_id=%s code=%s", user_id, integ.id, exc.code)
        raise SyncFailed(exc.code, exc.user_message, exc.http_status)

    try:
        # 3. Dedup on headers, before downloading any body.
        items = []
        for rec in headers:
            h = parse_headers(rec.literal or b"")
            fallback = f"{integ.host}|{mailbox}|{uidvalidity or 'none'}|{rec.uid}"
            items.append((rec, h, message_key(h.message_id, fallback)))
        summary.scanned = len(items)

        existing: set[str] = set()
        keys = [k for _, _, k in items]
        for i in range(0, len(keys), 500):
            chunk = keys[i:i + 500]
            rows = await db.execute(
                select(EmailMessage.message_key).where(
                    EmailMessage.user_id == user_id, EmailMessage.message_key.in_(chunk)
                )
            )
            existing.update(rows.scalars().all())

        fresh, seen = [], set()
        for rec, h, key in items:
            if key in existing or key in seen:
                summary.skipped_duplicates += 1
                continue
            seen.add(key)
            fresh.append((rec, h, key, effective_received_at(rec.internal_date, h.date)))
        # Oldest first, so a later email (e.g. interview) builds on an earlier one (application).
        epoch = datetime.min.replace(tzinfo=timezone.utc)
        fresh.sort(key=lambda t: (t[3] or epoch, t[0].uid or 0))

        # 4. Process.
        use_ai = ai_client is not None or ai_enabled()
        stopped_early = False
        for rec, h, key, received in fresh:
            if time.monotonic() > deadline:
                stopped_early = True
                summary.message = TIME_LIMIT_MESSAGE
                break

            row = EmailMessage(
                user_id=user_id,
                integration_id=integ.id,
                message_key=key,
                provider_message_id=h.message_id,
                provider_uid=rec.uid,
                thread_id=rec.thread_id,
                received_at=received,
                category="unrelated",
                is_job_related=False,
                processing_status="processed",
            )
            result = None

            if prefilter(h):
                try:
                    raw = await asyncio.to_thread(session.fetch_body, rec.uid, settings.EMAIL_SYNC_MAX_BODY_BYTES)
                except MailboxError:
                    summary.errors += 1        # not stored → retried on the next sync
                    continue
                except EmailProviderError:
                    summary.errors += 1        # connection-level problem: stop, keep progress
                    stopped_early = True
                    summary.message = PARTIAL_MESSAGE
                    break
                try:
                    parsed = parse_message(raw)
                    received_date = received.date() if received else None
                    result = classify(parsed, received_date)
                    if use_ai and summary.ai_used < settings.EMAIL_AI_MAX_PER_SYNC:
                        summary.ai_used += 1
                        result = merge(await ai_classify(parsed, received_date, client=ai_client), result)
                    row.category = result.category
                    row.confidence = result.confidence
                    row.classification_method = result.method
                    if result.is_job_related:
                        row.is_job_related = True
                        row.sender_email = parsed.sender_email or h.sender_email
                        row.sender_name = parsed.sender_name or h.sender_name
                        row.subject = (parsed.subject or h.subject or None) and (parsed.subject or h.subject)[:500]
                        row.snippet = parsed.snippet or None
                        row.body_text = parsed.body_text or None
                except Exception as exc:
                    logger.warning("email.sync.message_error user_id=%s uid=%s error=%s", user_id, rec.uid, type(exc).__name__)
                    summary.errors += 1
                    row.processing_status = "error"
                    result = None

            db.add(row)
            await db.flush()
            summary.new_messages += 1
            if row.is_job_related:
                summary.job_related += 1
                if result is not None and result.is_actionable:
                    outcome = await record_suggestion(db, user_id, row, result)
                    if outcome == "created":
                        summary.new_suggestions += 1
                    elif outcome == "merged":
                        summary.updated_suggestions += 1
                    await db.flush()
    finally:
        await _close(session)

    # 5. Bookkeeping.
    summary.status = "partial" if (stopped_early or summary.errors) else "success"
    if summary.status == "partial" and not summary.message:
        summary.message = PARTIAL_MESSAGE
    now = utcnow()
    integ.sync_lock_until = None
    integ.last_sync_at = now
    integ.last_verified_at = now
    integ.status = "connected"
    integ.status_detail = None
    integ.last_sync_status = summary.status
    integ.last_sync_error = summary.message[:255] if summary.status == "partial" else None
    integ.last_sync_scanned = summary.scanned
    integ.last_sync_new_messages = summary.new_messages
    integ.last_sync_job_related = summary.job_related
    integ.last_sync_new_suggestions = summary.new_suggestions
    await db.commit()
    logger.info(
        "email.sync.done user_id=%s integration_id=%s status=%s scanned=%s new=%s job_related=%s suggestions=%s errors=%s",
        user_id, integ.id, summary.status, summary.scanned, summary.new_messages,
        summary.job_related, summary.new_suggestions, summary.errors,
    )
    return summary
