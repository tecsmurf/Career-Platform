"""
Apply Assistant models — job intelligence, tailored applications, review.

All of these are NEW tables (the app creates tables with `create_all`, which
cannot alter existing ones), linked to `users` and, optionally, to the user's
tracker `jobs`.

    apply_profiles            1 per user: headline, targets, links, extra skills
    apply_resumes             base resume versions + tailored versions (never overwritten)
    apply_discovery_sources   public job boards (Greenhouse / Lever / Ashby) a user follows
    apply_postings            analysed job postings (intake by link/text, or discovered)
    apply_packages            prepared applications awaiting review (payload + sha256 hash)
    apply_package_events      append-only log of every review decision
    apply_ai_usage            ledger of AI calls (tokens + cost) — budgets are enforced on it
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


PACKAGE_STATUSES = ("ready_for_review", "approved", "rejected", "sent", "superseded")
POSTING_STATUSES = ("analyzed", "duplicate", "archived")
SOURCE_TYPES = ("manual", "url", "greenhouse", "lever", "ashby")


class ApplyProfile(Base):
    __tablename__ = "apply_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    headline: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    years_experience: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    target_roles_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    target_locations_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    open_to_remote: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    location: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    linkedin_url: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    github_url: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    portfolio_url: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    website_url: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    skills_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class ApplyDiscoverySource(Base):
    __tablename__ = "apply_discovery_sources"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", "board_token", name="uq_apply_sources_user_board"),
        CheckConstraint("provider IN ('greenhouse', 'lever', 'ashby')", name="ck_apply_sources_provider"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    board_token: Mapped[str] = mapped_column(String(100), nullable=False)
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    keywords_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    locations_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    last_new_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ApplyPosting(Base):
    __tablename__ = "apply_postings"
    __table_args__ = (
        # The same posting text once per user, and the same board posting once per user.
        UniqueConstraint("user_id", "content_hash", name="uq_apply_postings_user_hash"),
        UniqueConstraint("user_id", "source_type", "source_job_id", name="uq_apply_postings_user_source"),
        CheckConstraint("fit_score IS NULL OR (fit_score >= 0 AND fit_score <= 100)", name="ck_apply_postings_fit"),
        CheckConstraint("status IN ('analyzed', 'duplicate', 'archived')", name="ck_apply_postings_status"),
        CheckConstraint(
            "source_type IN ('manual', 'url', 'greenhouse', 'lever', 'ashby')", name="ck_apply_postings_source"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    source_job_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    discovery_source_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("apply_discovery_sources.id", ondelete="SET NULL"), nullable=True
    )
    listing_url: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    apply_url: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    company: Mapped[str] = mapped_column(String(300), nullable=False)
    location: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    location_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    analysis_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    match_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    research_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    injection_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fit_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="analyzed", index=True)
    tracked_job_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    analyzed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class ApplyResume(Base):
    __tablename__ = "apply_resumes"
    __table_args__ = (
        UniqueConstraint("user_id", "kind", "version", name="uq_apply_resumes_user_kind_version"),
        CheckConstraint("kind IN ('base', 'tailored')", name="ck_apply_resumes_kind"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Tailored versions: which posting, and which base version they came from.
    posting_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("apply_postings.id", ondelete="SET NULL"), nullable=True
    )
    base_resume_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("apply_resumes.id", ondelete="SET NULL"), nullable=True
    )
    changes_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ApplyPackage(Base):
    """
    A prepared application: tailored resume, cover letter, answers and
    (when the posting names a contact with an email) an outreach email.

    Review binds to the exact content: `payload_hash` is the sha256 of the
    canonical JSON payload; approving requires the client to send the hash it
    reviewed, and any edit produces a new hash and voids an earlier approval.
    Nothing is ever sent by the server — "approved" freezes a copy-ready final
    version (`final_json`) that the user sends or submits themselves.
    """

    __tablename__ = "apply_packages"
    __table_args__ = (
        UniqueConstraint("posting_id", "version", name="uq_apply_packages_posting_version"),
        CheckConstraint(
            "status IN ('ready_for_review', 'approved', 'rejected', 'sent', 'superseded')",
            name="ck_apply_packages_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    posting_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("apply_postings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ready_for_review", index=True)
    resume_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("apply_resumes.id", ondelete="SET NULL"), nullable=True
    )
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    approved_payload_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    final_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_channel: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    guard_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    generation_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class ApplyPackageEvent(Base):
    """Append-only: created, edited (approval voided), approved, rejected, marked sent, superseded."""

    __tablename__ = "apply_package_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    package_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("apply_packages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    payload_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ApplyAIUsage(Base):
    __tablename__ = "apply_ai_usage"
    __table_args__ = (Index("ix_apply_ai_usage_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    feature: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
