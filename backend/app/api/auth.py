"""
Authentication Endpoints — Register, Login, Get Profile, Email Settings
========================================================================

Flow:
    POST /api/auth/register        → validate domain → hash password → store → return JWT
    POST /api/auth/login           → find user → verify password → return JWT
    GET  /api/auth/me              → decode JWT → fetch user from DB → return profile

Mailbox (email integration) credentials are a separate system and live under
/api/email/* — they are never used to authenticate to the platform.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.user import UserCreate, UserResponse, Token
from app.services import auth_service

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


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
async def get_me(current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Get the current authenticated user's profile."""
    from app.services.email.integration import has_active_integration

    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        created_at=current_user.created_at.isoformat(),
        has_email_configured=await has_active_integration(db, current_user.id),
    )
