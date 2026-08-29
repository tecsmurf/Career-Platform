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
from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    """Schema for user registration request."""
    email: str = Field(..., min_length=5, max_length=100, examples=["alice@example.com"])
    password: str = Field(..., min_length=6, max_length=100, examples=["securepassword123"])
    full_name: str = Field(..., min_length=1, max_length=100, examples=["Alice Johnson"])


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


class EmailSettingsSave(BaseModel):
    """Schema for saving email sync settings."""
    email_user: str = Field(..., min_length=5, max_length=255, examples=["your-email@gmail.com"])
    email_app_password: str = Field(..., min_length=1, max_length=255, examples=["abcd efgh ijkl mnop"])
    email_host: str = Field(default="imap.gmail.com", max_length=255)


class EmailSettingsResponse(BaseModel):
    """Schema for returning email settings (no password)."""
    email_user: str | None = None
    email_host: str = "imap.gmail.com"
    is_configured: bool = False


class Token(BaseModel):
    """JWT token response."""
    access_token: str
    token_type: str = "bearer"
