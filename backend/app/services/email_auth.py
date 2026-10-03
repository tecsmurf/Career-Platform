"""
Account email verification and password reset with 6-digit codes.

Codes
-----
* 6 random digits (``secrets``), valid for AUTH_CODE_TTL_MINUTES, single use.
* Only ``HMAC-SHA256(SECRET_KEY, "purpose:user_id:code")`` is stored, so a
  database leak does not reveal live codes.
* Each code accepts AUTH_CODE_MAX_ATTEMPTS guesses (default 3). The attempt is
  counted with an atomic conditional UPDATE and committed BEFORE the code is
  compared, so parallel guesses cannot exceed the limit and a failed guess
  survives the request's rollback. Only the newest delivered code is checked.
* Issuing is limited per account and purpose — one code per
  AUTH_CODE_RESEND_SECONDS, AUTH_CODE_MAX_PER_HOUR per hour and
  AUTH_CODE_MAX_PER_DAY per day — and globally by MAIL_DAILY_SEND_LIMIT.
  Codes for accounts that signed up but never verified come out of a separate
  MAIL_DAILY_SIGNUP_LIMIT share, whatever triggered them, so fake sign-ups
  cannot use up the emails that verified and pre-existing accounts need.
  Issuing is serialised per account (row lock on PostgreSQL plus an
  in-process lock), so parallel requests cannot slip past these limits.
* The code row is committed BEFORE the provider call (no database connection
  is held while waiting for the email API) but only counts as the current
  code once ``sent_at`` is set after the provider accepted it. If sending
  fails — or anything else goes wrong — the row is removed again; a row left
  behind by a crash is ignored once the send window has passed.

Tickets
-------
Two short-lived signed tickets bind a code to whoever asked for it:

* Verification: handed out only after the password was presented (sign-up or
  sign-in) and required to verify. Whoever pre-registers someone else's
  address can never get the owner to verify it for them; the owner reclaims
  the address with a password reset, which also counts as verification.
* Password reset: returned by forgot-password for ANY address (so it reveals
  nothing). Reset codes are bound to the ticket they were requested with:
  wrong guesses and newer requests made by someone else (with their own
  ticket) neither burn nor replace the owner's code.

State
-----
``user_auth_state`` holds ``email_verified_at``, ``token_version`` and
``signup_pending``. Users without a row (everyone created before this feature)
count as unverified with version 0, so they verify at their next sign-in
once account email is on.
"""
from __future__ import annotations

import asyncio
import enum
import hashlib
import hmac
import secrets
import weakref
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import EmailCode, User, UserAuthState
from app.services.mailer import BrevoMailer, MailerError, build_code_email

VERIFY = "verify_email"
RESET = "reset_password"
TICKET_TYPE = "email_verification"
RESET_TICKET_TYPE = "password_reset"
_RETENTION = timedelta(days=7)
# Striped in-process locks (bounded memory) that serialise issuing per account
# within this process; PostgreSQL row locks cover other processes. One set per
# event loop, because an asyncio.Lock must not be shared between loops.
_LOCK_STRIPES = 64
_issue_locks: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, list[asyncio.Lock]]" = weakref.WeakKeyDictionary()


def _issue_lock(user_id: int) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    locks = _issue_locks.get(loop)
    if locks is None:
        locks = _issue_locks[loop] = [asyncio.Lock() for _ in range(_LOCK_STRIPES)]
    return locks[user_id % _LOCK_STRIPES]


class CodeLimitError(Exception):
    """Too many codes requested for this account recently."""

    def __init__(self, retry_after: int) -> None:
        super().__init__("code limit reached")
        self.retry_after = max(1, int(retry_after))


class MailQuotaError(Exception):
    """The platform-wide daily email limit (or the sign-up share of it) is reached."""

    def __init__(self, signup: bool = False) -> None:
        super().__init__("daily email limit reached")
        self.signup = signup


class IssueOutcome(enum.Enum):
    SENT = "sent"
    RECENTLY_SENT = "recently_sent"  # within the resend window; the previous code is still valid


@dataclass
class IssueResult:
    outcome: IssueOutcome
    retry_after: int = 0


@dataclass(frozen=True)
class AuthSnapshot:
    """Token version and verification state read in the same statement as the password hash."""
    token_version: int
    verified: bool


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    # SQLite returns naive datetimes (stored as UTC); PostgreSQL returns aware ones.
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def code_hash(purpose: str, user_id: int, code: str) -> str:
    message = f"{purpose}:{user_id}:{code}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


def new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


# ---------------------------------------------------------------------------
# Verification tickets
# ---------------------------------------------------------------------------
def make_ticket(user_id: int, token_version: int) -> str:
    now = _now()
    claims = {
        "typ": TICKET_TYPE, "uid": user_id, "tv": token_version, "iat": now,
        "exp": now + timedelta(minutes=settings.AUTH_VERIFY_TICKET_MINUTES),
    }
    return jwt.encode(claims, settings.SECRET_KEY, algorithm="HS256")


def _decode(ticket: str) -> dict | None:
    try:
        return jwt.decode(ticket or "", settings.SECRET_KEY, algorithms=["HS256"])
    except JWTError:
        return None


def read_ticket(ticket: str) -> tuple[int, int] | None:
    """(user_id, token_version) from a valid, unexpired verification ticket — else None."""
    claims = _decode(ticket)
    if not claims:
        return None
    uid, tv = claims.get("uid"), claims.get("tv")
    if claims.get("typ") != TICKET_TYPE or not isinstance(uid, int) or not isinstance(tv, int):
        return None
    return uid, tv


def make_reset_ticket(email: str) -> str:
    """Issued by forgot-password for any address; binds reset codes to the requester."""
    now = _now()
    claims = {
        # The address as typed (stripped): the same lookup then runs at reset
        # time as at request time, also for legacy mixed-case accounts.
        "typ": RESET_TICKET_TYPE, "em": (email or "").strip()[:255], "sid": secrets.token_hex(16), "iat": now,
        "exp": now + timedelta(minutes=settings.AUTH_VERIFY_TICKET_MINUTES),
    }
    return jwt.encode(claims, settings.SECRET_KEY, algorithm="HS256")


def read_reset_ticket(ticket: str) -> tuple[str, str] | None:
    """(email as typed, ticket hash) from a valid reset ticket — else None."""
    claims = _decode(ticket)
    if not claims:
        return None
    email, sid = claims.get("em"), claims.get("sid")
    if claims.get("typ") != RESET_TICKET_TYPE or not isinstance(email, str) or not isinstance(sid, str) or not sid:
        return None
    return email, hashlib.sha256(sid.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Users and state
# ---------------------------------------------------------------------------
async def find_user(db: AsyncSession, email: str) -> User | None:
    """Exact match first (accounts are stored as entered before normalisation
    existed), then a case-insensitive match — only if it is unambiguous."""
    raw = (email or "").strip()
    if not raw or len(raw) > 255:
        return None
    exact = (await db.execute(select(User).where(User.email == raw))).scalar_one_or_none()
    if exact is not None:
        return exact
    rows = (
        await db.execute(select(User).where(func.lower(User.email) == normalize_email(raw)).limit(2))
    ).scalars().all()
    return rows[0] if len(rows) == 1 else None


async def email_taken(db: AsyncSession, email: str) -> bool:
    found = await db.execute(select(User.id).where(func.lower(User.email) == normalize_email(email)).limit(1))
    return found.first() is not None


async def snapshot(db: AsyncSession, user_id: int) -> tuple[str, AuthSnapshot] | None:
    """(password hash, auth snapshot) from ONE statement, so a password reset
    committing in between cannot pair the old password with the new token version."""
    row = (
        await db.execute(
            select(User.hashed_password, UserAuthState.token_version, UserAuthState.email_verified_at)
            .outerjoin(UserAuthState, UserAuthState.user_id == User.id)
            .where(User.id == user_id)
        )
    ).first()
    if row is None:
        return None
    return row[0], AuthSnapshot(token_version=int(row[1] or 0), verified=row[2] is not None)


async def get_state(db: AsyncSession, user_id: int) -> UserAuthState | None:
    return await db.get(UserAuthState, user_id)


async def ensure_state(db: AsyncSession, user_id: int, *, signup_pending: bool = False) -> UserAuthState:
    state = await get_state(db, user_id)
    if state is not None:
        return state
    try:
        async with db.begin_nested():
            state = UserAuthState(user_id=user_id, token_version=0, signup_pending=signup_pending)
            db.add(state)
    except IntegrityError:  # created concurrently by another request
        state = await get_state(db, user_id)
        if state is None:
            raise
    return state


def is_verified(state: UserAuthState | None) -> bool:
    return bool(state and state.email_verified_at)


def token_version(state: UserAuthState | None) -> int:
    return int(state.token_version) if state else 0


async def mark_verified(db: AsyncSession, user_id: int) -> UserAuthState:
    state = await ensure_state(db, user_id)
    if state.email_verified_at is None:
        state.email_verified_at = _now()
    state.signup_pending = False
    await db.flush()
    return state


async def bump_token_version(db: AsyncSession, user_id: int) -> int:
    await ensure_state(db, user_id)
    await db.execute(
        update(UserAuthState)
        .where(UserAuthState.user_id == user_id)
        .values(token_version=UserAuthState.token_version + 1, updated_at=_now())
    )
    await db.flush()
    state = await get_state(db, user_id)
    await db.refresh(state)
    return int(state.token_version)


async def discard_new_user(db: AsyncSession, user_id: int) -> None:
    """Remove an account created moments ago in this request whose
    verification email could not be sent (so the address can register again)."""
    try:
        await db.rollback()
        await db.execute(delete(EmailCode).where(EmailCode.user_id == user_id))
        await db.execute(delete(UserAuthState).where(UserAuthState.user_id == user_id))
        await db.execute(delete(User).where(User.id == user_id))
        await db.commit()
    except Exception:
        # Left behind only if the database itself failed; the owner can still
        # sign in (which emails a code) or reset the password.
        pass


# ---------------------------------------------------------------------------
# Issuing codes
# ---------------------------------------------------------------------------
def _inflight_window() -> timedelta:
    # How long an unsent row may still be waiting for the provider.
    return timedelta(seconds=settings.MAIL_TIMEOUT_SECONDS + 5)


def _counts(now: datetime):
    """Rows that count for limits: delivered, or possibly still being sent."""
    return or_(EmailCode.sent_at.is_not(None), EmailCode.created_at > now - _inflight_window())


async def _check_limits(db: AsyncSession, user_id: int, purpose: str, pool: str, ticket_hash: str | None,
                        now: datetime) -> IssueResult | None:
    recent = (
        await db.execute(
            select(EmailCode.created_at, EmailCode.ticket_hash)
            .where(EmailCode.user_id == user_id, EmailCode.purpose == purpose,
                   EmailCode.created_at >= now - timedelta(days=1), _counts(now))
            .order_by(EmailCode.created_at.desc())
        )
    ).all()
    stamps = [_aware(r[0]) for r in recent]
    # Cooldown: per account, or per ticket for reset codes (so someone else's
    # request cannot stop the owner from getting a code for their own ticket).
    same_scope = [_aware(r[0]) for r in recent if ticket_hash is None or r[1] == ticket_hash]
    if same_scope:
        since_last = (now - same_scope[0]).total_seconds()
        if since_last < settings.AUTH_CODE_RESEND_SECONDS:
            return IssueResult(IssueOutcome.RECENTLY_SENT, int(settings.AUTH_CODE_RESEND_SECONDS - since_last) + 1)
    last_hour = [t for t in stamps if t >= now - timedelta(hours=1)]
    if len(last_hour) >= settings.AUTH_CODE_MAX_PER_HOUR:
        raise CodeLimitError((last_hour[-1] + timedelta(hours=1) - now).total_seconds() + 1)
    if len(stamps) >= settings.AUTH_CODE_MAX_PER_DAY:
        raise CodeLimitError((stamps[-1] + timedelta(days=1) - now).total_seconds() + 1)

    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today = (EmailCode.created_at >= day_start, _counts(now))
    if settings.MAIL_DAILY_SEND_LIMIT:
        sent_today = (await db.execute(select(func.count(EmailCode.id)).where(*today))).scalar_one()
        if sent_today >= settings.MAIL_DAILY_SEND_LIMIT:
            raise MailQuotaError()
    if pool == "signup" and settings.MAIL_DAILY_SIGNUP_LIMIT:
        signups_today = (
            await db.execute(select(func.count(EmailCode.id)).where(*today, EmailCode.pool == "signup"))
        ).scalar_one()
        if signups_today >= settings.MAIL_DAILY_SIGNUP_LIMIT:
            raise MailQuotaError(signup=True)
    return None


async def _forget_row(db: AsyncSession, row_id: int) -> None:
    try:
        await db.rollback()
        await db.execute(delete(EmailCode).where(EmailCode.id == row_id))
        await db.commit()
    except Exception:  # best effort: an unsent row stops counting after the send window anyway
        pass


async def issue_code(db: AsyncSession, mailer: BrevoMailer, user: User, purpose: str, *,
                     ticket_hash: str | None = None) -> IssueResult:
    """Create and send a new code for ``user``.

    Returns RECENTLY_SENT without sending when the previous code (for this
    account, or for this reset ticket) is younger than the resend window —
    nothing is committed then. Raises CodeLimitError / MailQuotaError when
    limits are reached (nothing committed) and MailerError if the provider
    did not accept the email.

    Once a code row is created the session is COMMITTED — including anything
    the caller added before (e.g. a new user). If sending fails for any reason
    the row is removed again (and committed) before the error propagates;
    earlier codes stay valid.
    """
    if purpose not in (VERIFY, RESET) or (purpose == RESET) != (ticket_hash is not None):
        raise ValueError("reset codes need a ticket; verification codes must not have one")
    async with _issue_lock(user.id):
        state = await ensure_state(db, user.id)
        # Serialise per account across processes (SQLite ignores FOR UPDATE;
        # the in-process lock above covers the single-process case).
        await db.execute(select(UserAuthState.user_id).where(UserAuthState.user_id == user.id).with_for_update())
        pool = "signup" if state.signup_pending else "general"
        now = _now()
        limited = await _check_limits(db, user.id, purpose, pool, ticket_hash, now)
        if limited is not None:
            return limited

        code = new_code()
        row = EmailCode(
            user_id=user.id, purpose=purpose, pool=pool, ticket_hash=ticket_hash,
            code_hash=code_hash(purpose, user.id, code), sent_to=user.email,
            expires_at=now + timedelta(minutes=settings.AUTH_CODE_TTL_MINUTES), attempts=0, created_at=now,
        )
        db.add(row)
        await db.commit()  # counts for every limit from now on; the connection is released
        row_id = row.id

    message = build_code_email(purpose=purpose, code=code, to_email=user.email,
                               ttl_minutes=settings.AUTH_CODE_TTL_MINUTES)
    sent = False
    try:
        await mailer.send(message)
        sent = True
    finally:
        if not sent:
            await _forget_row(db, row_id)

    # Delivered: this becomes the current code and replaces earlier ones
    # (for reset codes: only earlier ones requested with the same ticket).
    sent_at = _now()
    await db.execute(update(EmailCode).where(EmailCode.id == row_id).values(sent_at=sent_at))
    older = [EmailCode.user_id == user.id, EmailCode.purpose == purpose,
             EmailCode.id != row_id, EmailCode.consumed_at.is_(None)]
    if ticket_hash is not None:
        older.append(EmailCode.ticket_hash == ticket_hash)
    await db.execute(update(EmailCode).where(*older).values(consumed_at=sent_at))
    await db.execute(delete(EmailCode).where(EmailCode.created_at < now - _RETENTION))
    await db.commit()
    return IssueResult(IssueOutcome.SENT, settings.AUTH_CODE_RESEND_SECONDS)


# ---------------------------------------------------------------------------
# Checking codes
# ---------------------------------------------------------------------------
async def check_code(db: AsyncSession, user: User, purpose: str, code: str, *,
                     ticket_hash: str | None = None) -> bool:
    """True exactly once for the current (newest delivered, unexpired) correct
    code — for reset codes, the current code of that ticket.

    Every guess against a live code is counted and committed first.
    """
    if len(code or "") != 6 or not code.isdigit():
        return False
    if (purpose == RESET) != (ticket_hash is not None):
        return False
    now = _now()
    conditions = [EmailCode.user_id == user.id, EmailCode.purpose == purpose, EmailCode.sent_at.is_not(None),
                  EmailCode.consumed_at.is_(None), EmailCode.expires_at > now]
    if ticket_hash is not None:
        conditions.append(EmailCode.ticket_hash == ticket_hash)
    row = (
        await db.execute(
            select(EmailCode).where(*conditions)
            .order_by(EmailCode.created_at.desc(), EmailCode.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return False

    counted = await db.execute(
        update(EmailCode)
        .where(EmailCode.id == row.id, EmailCode.consumed_at.is_(None),
               EmailCode.attempts < settings.AUTH_CODE_MAX_ATTEMPTS)
        .values(attempts=EmailCode.attempts + 1)
    )
    await db.commit()
    if counted.rowcount != 1:
        return False  # out of attempts (or used concurrently)

    if not hmac.compare_digest(row.code_hash, code_hash(purpose, user.id, code)):
        return False

    consumed = await db.execute(
        update(EmailCode)
        .where(EmailCode.id == row.id, EmailCode.consumed_at.is_(None))
        .values(consumed_at=now)
    )
    await db.flush()
    return consumed.rowcount == 1


async def consume_all(db: AsyncSession, user_id: int) -> None:
    """Invalidate every outstanding code of a user (after a password reset)."""
    await db.execute(
        update(EmailCode)
        .where(EmailCode.user_id == user_id, EmailCode.consumed_at.is_(None))
        .values(consumed_at=_now())
    )
    await db.flush()
