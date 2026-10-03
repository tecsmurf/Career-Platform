"""
Authentication Endpoints — Register, Login, Email Verification, Password Reset
==============================================================================

Flow:
    GET  /api/auth/config               → which email features are switched on
    POST /api/auth/register             → validate domain → hash password → store
                                          → (email auth on)  email a 6-digit code; reply with a
                                            verification ticket, no session yet
                                          → (email auth off) return JWT
    POST /api/auth/login                → rate-limit → verify password
                                          → unverified (email auth on): 403 email_not_verified
                                            + ticket (and a code is emailed)
                                          → return JWT
    POST /api/auth/verify-email         → ticket + code → mark verified → JWT
    POST /api/auth/resend-verification  → ticket → new verification code
    POST /api/auth/forgot-password      → email → reset ticket (for any address) and,
                                          if the account exists, a reset code bound to it
    POST /api/auth/reset-password       → reset ticket + code + new password → JWT
                                          (every older session ends)
    GET  /api/auth/me                   → decode JWT → fetch user → profile

Tickets (short-lived signed tokens, never sessions):
* the verification ticket is handed out only after the password was
  presented and is required to verify — so whoever pre-registers someone
  else's address can never get the real owner to verify it for them; the
  owner takes the address back through password reset, which also counts as
  verification;
* the reset ticket binds reset codes to whoever requested them, so a
  stranger's wrong guesses or new requests cannot burn or replace the owner's
  code.

"Email auth on" means EMAIL_AUTH_ENABLED plus a Brevo API key and sender
address (see app/core/config.py). Without them everything behaves as before
and the code endpoints answer 503 — nothing pretends that an email was sent.

Mailbox (email integration) credentials are a separate system and live under
/api/email/* — they are never used to authenticate to the platform.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.rate_limit import SlidingWindowLimiter
from app.database import get_db
from app.models import User, UserAuthState
from app.schemas.user import (
    AuthConfig, ForgotPasswordIn, MessageOut, RegisterResponse, ResetPasswordIn, ResetRequestOut, TicketIn,
    Token, UserCreate, UserResponse, VerifyEmailIn,
)
from app.services import auth_service, email_auth
from app.services.email_auth import RESET, VERIFY, CodeLimitError, IssueOutcome, MailQuotaError
from app.services.login_limiter import RATE_LIMITED_DETAIL, client_ip, login_limiter
from app.services.mailer import BrevoMailer, MailerError, get_mailer

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

# In-process throttles for the code endpoints. The database limits in
# email_auth (guesses per code, codes per account, daily quota) are the
# primary control; these only stop hammering.
verify_account_limiter = SlidingWindowLimiter(10, 900)  # per account, keyed from the ticket
code_check_ip_limiter = SlidingWindowLimiter(60, 900)   # verify / reset guesses per client IP
code_send_ip_limiter = SlidingWindowLimiter(20, 900)    # resend / forgot-password per client IP
register_ip_limiter = SlidingWindowLimiter(10, 3600)    # only while account email is on
ALL_AUTH_LIMITERS = (verify_account_limiter, code_check_ip_limiter, code_send_ip_limiter, register_ip_limiter)


def _detail(code: str, message: str, **extra) -> dict:
    return {"code": code, "message": message, **extra}


INVALID_CODE = _detail(
    "invalid_code", "That code is incorrect or has expired. Use the latest code we emailed you, or request a new one."
)
TICKET_EXPIRED = _detail(
    "verification_expired", "This verification step has expired. Sign in again and we'll send you a new code."
)
RESET_EXPIRED = _detail(
    "reset_expired", "This reset request has expired. Request a new code to continue."
)
TOO_MANY = _detail("rate_limited", "Too many attempts. Please wait a few minutes and try again.")


def _throttle(limiter: SlidingWindowLimiter, key) -> None:
    if key is None:
        return
    retry = limiter.hit(key)
    if retry is not None:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail=TOO_MANY, headers={"Retry-After": str(retry)})


def _ip_key(request: Request) -> str | None:
    # Same rule as the login limiter: behind a proxy without CLIENT_IP_HEADER
    # every request shares one address, so per-IP limits are skipped there.
    return client_ip(request) if settings.login_ip_limit_active else None


def _require_email_auth(mailer: BrevoMailer | None) -> BrevoMailer:
    if not settings.email_auth_active or mailer is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_detail("email_auth_unavailable",
                           "Email codes aren't set up on this server, so this isn't available right now."),
        )
    return mailer


def _token_for(user: User, tv: int) -> dict:
    token = auth_service.create_access_token({"sub": user.email, "user_id": user.id, "tv": tv})
    return {"access_token": token, "token_type": "bearer"}


def _send_failed(exc: Exception) -> HTTPException:
    if isinstance(exc, MailQuotaError):
        message = ("New sign-ups are paused for today because the daily email limit was reached. "
                   "Please try again tomorrow." if exc.signup
                   else "Email sending is paused for today because the daily limit was reached. "
                        "Please try again tomorrow.")
    else:
        message = "We couldn't send the email right now. Please try again in a few minutes."
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=_detail("email_send_failed", message))


def _too_many_codes(exc: CodeLimitError) -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        detail=_detail("too_many_codes", "You've requested several codes already. Use the latest one you "
                                         "received, or try again later."),
        headers={"Retry-After": str(exc.retry_after)},
    )


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    """Dependency: extract and validate the current user from the JWT token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = auth_service.decode_token(token)
    if payload is None or "typ" in payload:  # verification tickets are not sessions
        raise credentials_exception

    user_id = payload.get("user_id")
    if not isinstance(user_id, int):
        raise credentials_exception

    row = (
        await db.execute(
            select(User, UserAuthState)
            .outerjoin(UserAuthState, UserAuthState.user_id == User.id)
            .where(User.id == user_id)
        )
    ).first()
    if row is None:
        raise credentials_exception
    user, state = row

    # Deactivated accounts must not be able to use existing tokens.
    if not getattr(user, "is_active", True):
        raise credentials_exception

    # A password reset bumps the version; tokens issued before it stop working.
    # (Tokens from before this feature carry no "tv" and count as version 0.)
    tv = payload.get("tv", 0)
    if not isinstance(tv, int) or tv != email_auth.token_version(state):
        raise credentials_exception

    # With account email on, only verified addresses get a session. Tokens
    # issued before it was switched on end here; the user signs in again and
    # is asked for a code.
    if settings.email_auth_active and not email_auth.is_verified(state):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Please verify your email address, then sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


@router.get("/config", response_model=AuthConfig)
async def auth_config():
    """Public: lets the sign-in pages show only the features that work."""
    active = settings.email_auth_active
    return AuthConfig(email_verification=active, password_reset=active,
                      resend_seconds=settings.AUTH_CODE_RESEND_SECONDS,
                      code_ttl_minutes=settings.AUTH_CODE_TTL_MINUTES)


@router.post("/register", response_model=RegisterResponse, response_model_exclude_none=True,
             status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    mailer: BrevoMailer | None = Depends(get_mailer),
):
    """Register a new user account."""
    email = email_auth.normalize_email(user_data.email)
    if settings.email_auth_active:
        _throttle(register_ip_limiter, _ip_key(request))

    # Verify the email domain can actually receive mail (blocks fake domains).
    domain = email.split("@")[-1]
    if not await auth_service.email_domain_deliverable(domain):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid email domain '{domain}'. Use a real email address.",
        )

    if await email_auth.email_taken(db, email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered. Sign in, or use “Forgot password?” to reset the password.",
        )

    user = await auth_service.create_user(
        db, email=email, password=user_data.password, full_name=user_data.full_name
    )
    if not settings.email_auth_active:
        return _token_for(user, 0)

    mailer = _require_email_auth(mailer)
    await email_auth.ensure_state(db, user.id, signup_pending=True)
    try:
        await email_auth.issue_code(db, mailer, user, VERIFY)
    except MailQuotaError as exc:
        raise _send_failed(exc) from None  # nothing committed: the new account rolls back
    except CodeLimitError:
        raise _send_failed(MailerError()) from None
    except BaseException as exc:
        # The account was committed together with the code; remove it again
        # so the same address can simply register once sending works.
        await email_auth.discard_new_user(db, user.id)
        if not isinstance(exc, MailerError):
            raise
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_detail("email_send_failed",
                           "We couldn't send the verification email, so the account wasn't created. "
                           "Please try again in a few minutes."),
        ) from None
    return RegisterResponse(
        verification_required=True, verification_ticket=email_auth.make_ticket(user.id, 0), email=user.email,
        message=f"We sent a 6-digit code to {user.email}. Enter it to finish creating your account.",
    )


@router.post("/login", response_model=Token)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
    mailer: BrevoMailer | None = Depends(get_mailer),
):
    """Login and receive a JWT token.

    Every request that reaches credential verification first takes one token
    from the per-account bucket (and the per-IP bucket). An empty bucket means
    429 before any database lookup or bcrypt work, with the same response
    whether or not the account exists.

    With account email on, a correct password for an unverified address
    answers 403 ``email_not_verified`` with a verification ticket (and emails
    a code) instead of a session.
    """
    retry_after = await login_limiter.check(account=form_data.username, ip=client_ip(request))
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=RATE_LIMITED_DETAIL,
            headers={"Retry-After": str(retry_after)},
        )

    found = await auth_service.authenticate_with_snapshot(db, form_data.username, form_data.password)
    if not found:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user, snap = found

    if settings.email_auth_active and mailer is not None and not snap.verified:
        outcome = "failed"
        if user.is_active:
            try:
                result = await email_auth.issue_code(db, mailer, user, VERIFY)
                outcome = "sent" if result.outcome is IssueOutcome.SENT else "recent"
            except CodeLimitError:
                outcome = "limited"
            except (MailerError, MailQuotaError):
                outcome = "failed"
        messages = {
            "sent": f"Please verify your email first. We just sent a 6-digit code to {user.email}.",
            "recent": f"Please verify your email first. We sent a code to {user.email} a moment ago.",
            "limited": f"Please verify your email first. Use the latest code we sent to {user.email}.",
            "failed": "Please verify your email first. We couldn't send a code just now — "
                      "use “Resend code” to try again.",
        }
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail=_detail("email_not_verified", messages[outcome], email=user.email,
                           email_sent=outcome in ("sent", "recent"),
                           ticket=email_auth.make_ticket(user.id, snap.token_version)),
        )

    return _token_for(user, snap.token_version)


async def _ticket_user(db: AsyncSession, ticket: str) -> User:
    """The account a verification ticket belongs to, if the ticket is still valid."""
    parsed = email_auth.read_ticket(ticket)
    if parsed is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=TICKET_EXPIRED)
    user_id, tv = parsed
    user = await auth_service.get_user_by_id(db, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=TICKET_EXPIRED)
    # A password reset since the ticket was issued ends it.
    if tv != email_auth.token_version(await email_auth.get_state(db, user.id)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=TICKET_EXPIRED)
    return user


@router.post("/verify-email", response_model=Token)
async def verify_email(data: VerifyEmailIn, request: Request, db: AsyncSession = Depends(get_db),
                       mailer: BrevoMailer | None = Depends(get_mailer)):
    _require_email_auth(mailer)
    _throttle(code_check_ip_limiter, _ip_key(request))
    user = await _ticket_user(db, data.ticket)
    _throttle(verify_account_limiter, user.id)

    if not await email_auth.check_code(db, user, VERIFY, data.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=INVALID_CODE)
    state = await email_auth.mark_verified(db, user.id)
    await db.commit()
    return _token_for(user, email_auth.token_version(state))


@router.post("/resend-verification", response_model=MessageOut)
async def resend_verification(data: TicketIn, request: Request, db: AsyncSession = Depends(get_db),
                              mailer: BrevoMailer | None = Depends(get_mailer)):
    """Needs the ticket from sign-up / sign-in, so it only ever emails the
    account holder who just presented their password."""
    mailer = _require_email_auth(mailer)
    _throttle(code_send_ip_limiter, _ip_key(request))
    user = await _ticket_user(db, data.ticket)
    if email_auth.is_verified(await email_auth.get_state(db, user.id)):
        return MessageOut(message="Your email is already verified. You can sign in.", resend_after=0)
    try:
        result = await email_auth.issue_code(db, mailer, user, VERIFY)
    except CodeLimitError as exc:
        raise _too_many_codes(exc) from None
    except (MailQuotaError, MailerError) as exc:
        raise _send_failed(exc) from None
    if result.outcome is IssueOutcome.SENT:
        message = f"We sent a new code to {user.email}. It can take a minute to arrive — check spam too."
    else:
        message = f"We sent a code to {user.email} moments ago. Check your inbox (and spam) before asking again."
    return MessageOut(message=message, resend_after=result.retry_after)


@router.post("/forgot-password", response_model=ResetRequestOut)
async def forgot_password(data: ForgotPasswordIn, request: Request, db: AsyncSession = Depends(get_db),
                          mailer: BrevoMailer | None = Depends(get_mailer)):
    """Returns a reset ticket for any address and, if the account exists,
    emails a code bound to that ticket.

    The reply is the same for unknown addresses and for codes sent or still
    within the resend window. It differs only when the account has hit its
    code limit (429) or the email could not be sent (503) — reporting those
    honestly matters more here, and /register already tells whether an
    address is registered.
    """
    mailer = _require_email_auth(mailer)
    _throttle(code_send_ip_limiter, _ip_key(request))
    email = data.email.strip()
    ticket = data.ticket
    parsed = email_auth.read_reset_ticket(ticket) if ticket else None
    if parsed is None or email_auth.normalize_email(parsed[0]) != email_auth.normalize_email(email):
        ticket = email_auth.make_reset_ticket(email)
        parsed = email_auth.read_reset_ticket(ticket)
    email, ticket_hash = parsed  # the ticket's address drives the lookup, here and at reset

    user = await email_auth.find_user(db, email)
    if user is not None and user.is_active:
        try:
            await email_auth.issue_code(db, mailer, user, RESET, ticket_hash=ticket_hash)
        except CodeLimitError as exc:
            raise _too_many_codes(exc) from None
        except (MailQuotaError, MailerError) as exc:
            raise _send_failed(exc) from None
    return ResetRequestOut(
        message="If an account exists for that email, a 6-digit reset code is on its way. "
                "It can take a minute — check spam too.",
        resend_after=settings.AUTH_CODE_RESEND_SECONDS,
        reset_ticket=ticket,
    )


@router.post("/reset-password", response_model=Token)
async def reset_password(data: ResetPasswordIn, request: Request, db: AsyncSession = Depends(get_db),
                         mailer: BrevoMailer | None = Depends(get_mailer)):
    """Set a new password with the reset ticket + code. Signs the user in and
    ends every other session (older tokens carry the previous token version).

    Guessing is bounded by the database (AUTH_CODE_MAX_ATTEMPTS per code, a
    few codes per day per account). Codes are bound to the ticket they were
    requested with, so a stranger's guesses cannot burn the owner's code, and
    there is deliberately no per-email throttle that could block the owner.
    """
    _require_email_auth(mailer)
    _throttle(code_check_ip_limiter, _ip_key(request))
    parsed = email_auth.read_reset_ticket(data.ticket)
    if parsed is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=RESET_EXPIRED)
    email, ticket_hash = parsed

    user = await email_auth.find_user(db, email)
    if user is None or not user.is_active or not await email_auth.check_code(
        db, user, RESET, data.code, ticket_hash=ticket_hash
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=INVALID_CODE)

    user.hashed_password = auth_service.hash_password(data.new_password)
    await email_auth.mark_verified(db, user.id)  # the code proved the mailbox is theirs
    version = await email_auth.bump_token_version(db, user.id)
    await email_auth.consume_all(db, user.id)
    await db.commit()
    return _token_for(user, version)


@router.get("/me", response_model=UserResponse)
async def get_me(current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Get the current authenticated user's profile."""
    from app.services.email.integration import has_active_integration

    state = await email_auth.get_state(db, current_user.id)
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        created_at=current_user.created_at.isoformat(),
        has_email_configured=await has_active_integration(db, current_user.id),
        email_verified=email_auth.is_verified(state),
    )
