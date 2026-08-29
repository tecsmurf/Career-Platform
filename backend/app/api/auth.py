"""
Authentication Endpoints — Register, Login, Get Profile, Email Settings
========================================================================

Now uses PostgreSQL via SQLAlchemy instead of in-memory dicts.

Flow:
    POST /api/auth/register        → hash password → store in PostgreSQL → return JWT
    POST /api/auth/login           → find user → verify password → return JWT
    GET  /api/auth/me              → decode JWT → fetch user from DB → return profile
    PUT  /api/auth/email-settings  → save per-user Gmail credentials
    GET  /api/auth/email-settings  → get email settings (no password)
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.user import UserCreate, UserResponse, Token, EmailSettingsSave, EmailSettingsResponse
from app.services import auth_service

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    """Dependency: extract and validate the current user from JWT token."""
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

    return user


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
async def register(user_data: UserCreate, db: AsyncSession = Depends(get_db)):
    """Register a new user account."""
    # Verify the email domain has real mail servers (blocks fake domains)
    import dns.resolver
    domain = user_data.email.split("@")[-1]
    try:
        dns.resolver.resolve(domain, "MX")
    except Exception:
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


@router.put("/email-settings", response_model=EmailSettingsResponse)
async def save_email_settings(
    settings_data: EmailSettingsSave,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save Gmail credentials for email sync (per-user). Password is encrypted."""
    from app.core.encryption import encrypt
    current_user.email_host = settings_data.email_host
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

