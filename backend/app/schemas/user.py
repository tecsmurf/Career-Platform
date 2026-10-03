"""
User Schemas — Pydantic Models for Request/Response Validation
==============================================================

Pydantic schemas define:
    1. What data the API ACCEPTS (request body validation)
    2. What data the API RETURNS (response serialization)
    3. What errors to show when data is invalid

Why Pydantic?
    Without it, you'd manually check every field:
        if "email" not in data: return error
        if "@" not in data["email"]: return error
        ...
    
    With Pydantic, you declare the shape once and it validates automatically.
    FastAPI uses Pydantic schemas to auto-generate API documentation too.

Schema naming convention:
    UserCreate   → for POST (what client sends to create a user)
    UserResponse → for GET  (what server sends back, NO password)
    UserUpdate   → for PUT  (what client sends to update)
"""
from typing import Optional

from pydantic import BaseModel, Field, field_validator


def _plain_email(value: str) -> str:
    value = (value or "").strip()
    local, at, domain = value.partition("@")
    if not at or not local or "." not in domain or "@" in domain or any(c.isspace() for c in value):
        raise ValueError("Enter a valid email address")
    return value


class UserCreate(BaseModel):
    """Schema for user registration request."""
    email: str = Field(..., min_length=5, max_length=100, examples=["alice@example.com"])
    password: str = Field(..., min_length=6, max_length=100, examples=["securepassword123"])
    full_name: str = Field(..., min_length=1, max_length=100, examples=["Alice Johnson"])

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _plain_email(v)

    @field_validator("full_name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("Enter your name")
        return v


class UserResponse(BaseModel):
    """
    Schema for user data in responses.
    
    NEVER include password or hashed_password in responses.
    This schema ensures you can't accidentally leak passwords.
    """
    id: int
    email: str
    full_name: str
    created_at: str
    has_email_configured: bool = False
    email_verified: bool = False


class Token(BaseModel):
    """JWT token response."""
    access_token: str
    token_type: str = "bearer"


class RegisterResponse(BaseModel):
    """Either a token (email verification off) or a pending-verification notice
    with the ticket needed on the code screen."""
    access_token: Optional[str] = None
    token_type: Optional[str] = None
    verification_required: bool = False
    verification_ticket: Optional[str] = None
    email: Optional[str] = None
    message: Optional[str] = None


class AuthConfig(BaseModel):
    email_verification: bool
    password_reset: bool
    code_length: int = 6
    resend_seconds: int
    code_ttl_minutes: int


class EmailIn(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)


class TicketIn(BaseModel):
    ticket: str = Field(..., min_length=10, max_length=2000)


class VerifyEmailIn(TicketIn):
    code: str = Field(..., pattern=r"^[0-9]{6}$")


class ForgotPasswordIn(EmailIn):
    # Sent again when the user asks for another code, so the new code belongs
    # to the reset request already open in their browser.
    ticket: Optional[str] = Field(None, max_length=2000)


class ResetPasswordIn(TicketIn):
    code: str = Field(..., pattern=r"^[0-9]{6}$")
    new_password: str = Field(..., min_length=6, max_length=100)


class MessageOut(BaseModel):
    message: str
    resend_after: int


class ResetRequestOut(MessageOut):
    reset_ticket: str
