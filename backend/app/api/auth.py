"""
Authentication Endpoints — Register, Login, Get Profile, Email Settings
========================================================================

Flow:
    POST /api/auth/register        → validate domain → hash password → store → return JWT
    POST /api/auth/login           → find user → verify password → return JWT
    GET  /api/auth/me              → decode JWT → fetch user from DB → return profile
    PUT  /api/auth/email-settings  → save per-user Gmail credentials (IMAP-verified)
    GET  /api/auth/email-settings  → get email settings (no password)
"""
import asyncio
import imaplib
import ipaddress
import socket

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import encrypt
from app.database import get_db
from app.schemas.user import UserCreate, UserResponse, Token, EmailSettingsSave, EmailSettingsResponse
from app.services import auth_service

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

IMAP_CONNECT_TIMEOUT = 10  # seconds


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
    if payload is None:
        raise credentials_exception

    user_id = payload.get("user_id")
    if user_id is None:
        raise credentials_exception

    user = await auth_service.get_user_by_id(db, user_id)
    if user is None:
        raise credentials_exception

    # Deactivated accounts must not be able to use existing tokens.
    if not getattr(user, "is_active", True):
        raise credentials_exception

    return user


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
async def register(user_data: UserCreate, db: AsyncSession = Depends(get_db)):
    """Register a new user account."""
    # Verify the email domain can actually receive mail (blocks fake domains).
    domain = user_data.email.split("@")[-1].strip().lower()
    if not await auth_service.email_domain_deliverable(domain):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid email domain '{domain}'. Use a real email address.",
        )

    existing = await auth_service.get_user_by_email(db, user_data.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = await auth_service.create_user(
        db, email=user_data.email, password=user_data.password, full_name=user_data.full_name
    )
    token = auth_service.create_access_token({"sub": user.email, "user_id": user.id})
    return {"access_token": token, "token_type": "bearer"}


@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """Login and receive a JWT token."""
    user = await auth_service.authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = auth_service.create_access_token({"sub": user.email, "user_id": user.id})
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me", response_model=UserResponse)
async def get_me(current_user=Depends(get_current_user)):
    """Get the current authenticated user's profile."""
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        created_at=current_user.created_at.isoformat(),
        has_email_configured=current_user.has_email_configured,
    )


# ---------------------------------------------------------------------------
# Email settings (IMAP) — hardened against SSRF and hangs
# ---------------------------------------------------------------------------
def _host_is_public(host: str) -> bool:
    """Resolve `host` and reject private/loopback/link-local/reserved targets.

    Prevents a user-supplied email_host from being used to probe internal
    infrastructure (SSRF) via the IMAP connection test.
    """
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, 993, proto=socket.IPPROTO_TCP)
    except Exception:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False
    return True


def _verify_imap_login(host: str, user: str, password: str) -> None:
    """Blocking IMAP login test (run via asyncio.to_thread)."""
    mail = imaplib.IMAP4_SSL(host, timeout=IMAP_CONNECT_TIMEOUT)
    try:
        mail.login(user, password)
    finally:
        try:
            mail.logout()
        except Exception:
            pass


@router.put("/email-settings", response_model=EmailSettingsResponse)
async def save_email_settings(
    settings_data: EmailSettingsSave,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save Gmail credentials for email sync (per-user). Verifies IMAP first."""
    host = (settings_data.email_host or "imap.gmail.com").strip()

    if not await asyncio.to_thread(_host_is_public, host):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or disallowed email host.",
        )

    # Test the connection BEFORE saving (off the event loop, with a timeout).
    try:
        await asyncio.to_thread(
            _verify_imap_login, host, settings_data.email_user, settings_data.email_app_password
        )
    except imaplib.IMAP4.error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Login failed. Check your email and app password. Make sure you're "
                "using a Gmail App Password, not your regular password."
            ),
        )
    except Exception:
        # Don't leak internal connection details back to the client.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not connect to email host '{host}'.",
        )

    # Connection works — save encrypted credentials.
    current_user.email_host = host
    current_user.email_user = settings_data.email_user
    current_user.email_app_password = encrypt(settings_data.email_app_password)
    db.add(current_user)
    await db.flush()
    return EmailSettingsResponse(
        email_user=current_user.email_user,
        email_host=current_user.email_host,
        is_configured=True,
    )


@router.get("/email-settings", response_model=EmailSettingsResponse)
async def get_email_settings(current_user=Depends(get_current_user)):
    """Get current email settings (password is never returned)."""
    return EmailSettingsResponse(
        email_user=current_user.email_user,
        email_host=current_user.email_host or "imap.gmail.com",
        is_configured=current_user.has_email_configured,
    )
