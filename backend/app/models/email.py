"""
Email Integration Models
========================

    users ──< email_integrations          (mailbox connections; credentials encrypted)
    users ──< email_messages               (safe metadata of synced emails, deduplicated)
    email_messages ──o job_suggestions     (extracted job info awaiting user review)

These are NEW tables, so `Base.metadata.create_all` creates them on startup
without altering any existing table (no migration risk for users/jobs).

Every row carries user_id and every query must be scoped by it.
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timeutil import utcnow
from app.database.connection import Base


class EmailIntegration(Base):
    __tablename__ = "email_integrations"
    __table_args__ = (
        UniqueConstraint("user_id", "email_address", name="uq_email_integration_user_address"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)          # gmail | imap
    email_address: Mapped[str] = mapped_column(String(320), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False, default=993)

    # Fernet ciphertext of {"password": ...} bound to (user_id, email_address).
    # NULL once disconnected.
    encrypted_credentials: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    # connected | needs_reconnect | disconnected
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="connected")
    status_detail: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    connected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Sync bookkeeping
    sync_lock_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_status: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # success|partial|failed
    last_sync_error: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_sync_scanned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_sync_new_messages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_sync_job_related: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_sync_new_suggestions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    def __repr__(self):  # never include credentials
        return f"<EmailIntegration(id={self.id}, user_id={self.user_id}, provider={self.provider}, status={self.status})>"


class EmailMessage(Base):
    __tablename__ = "email_messages"
    __table_args__ = (
        UniqueConstraint("user_id", "message_key", name="uq_email_message_user_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    integration_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("email_integrations.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Dedup key: sha256 of the normalized Message-ID (fallback: mailbox UID identity).
    message_key: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_message_id: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    provider_uid: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    thread_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Populated only for job-related emails (data minimisation for everything else).
    sender_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    sender_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    subject: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    snippet: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    body_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # plain text only, never HTML

    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    is_job_related: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="unrelated")
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    classification_method: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # rules | ai
    processing_status: Mapped[str] = mapped_column(String(16), nullable=False, default="processed")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class JobSuggestion(Base):
    __tablename__ = "job_suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("email_messages.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # new_job | status_update
    matched_job_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )

    # Extracted fields — NULL when not present in the email (never guessed).
    company: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    position: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    location: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    salary_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    job_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    applied_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    category: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    extraction_method: Mapped[str] = mapped_column(String(16), nullable=False, default="rules")

    review_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    created_job_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
