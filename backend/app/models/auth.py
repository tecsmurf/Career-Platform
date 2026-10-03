"""
Account-email tables: verification state and one-time codes.

New tables only (the app creates tables with ``create_all`` and has no
migrations), so nothing in ``users`` changes:

    user_auth_state                       email_codes
    ├── user_id (PK, FK → users.id)       ├── id (PK)
    ├── email_verified_at                 ├── user_id (FK → users.id)
    ├── token_version                     ├── purpose   verify_email | reset_password
    └── updated_at                        ├── code_hash HMAC-SHA256(SECRET_KEY, …) — never the code
                                          ├── sent_to
                                          ├── expires_at / consumed_at
                                          ├── attempts
                                          └── created_at

A user with no ``user_auth_state`` row is simply unverified with token
version 0 — that is how accounts created before this feature are treated.
``token_version`` is copied into every JWT ("tv"); bumping it (password reset)
invalidates every token issued before.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


CODE_PURPOSES = ("verify_email", "reset_password")


class UserAuthState(Base):
    __tablename__ = "user_auth_state"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # True for accounts created by sign-up while account email is on, until
    # verified: their emails count against the sign-up share of the quota.
    signup_pending: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class EmailCode(Base):
    __tablename__ = "email_codes"
    __table_args__ = (
        CheckConstraint("purpose IN ('verify_email', 'reset_password')", name="ck_email_codes_purpose"),
        CheckConstraint("attempts >= 0", name="ck_email_codes_attempts"),
        CheckConstraint("pool IN ('signup', 'general')", name="ck_email_codes_pool"),
        Index("ix_email_codes_user_purpose_created", "user_id", "purpose", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    pool: Mapped[str] = mapped_column(String(10), nullable=False)
    ticket_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    sent_to: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False, index=True)
