"""
Database Models — SQLAlchemy ORM
================================

These classes define your database tables.
Each class = one table. Each attribute = one column.

Database schema:

    users
    ├── id (PK)
    ├── email (unique)
    ├── full_name
    ├── hashed_password
    ├── is_active
    ├── created_at
    └── updated_at

    jobs
    ├── id (PK)
    ├── user_id (FK → users.id)
    ├── company
    ├── position
    ├── status
    ├── job_url
    ├── salary_min
    ├── salary_max
    ├── location
    ├── notes
    ├── applied_date
    ├── created_at
    └── updated_at

Relationship: One user → Many jobs (1:N)
"""
from datetime import datetime, timezone, date
from typing import Optional, List

from sqlalchemy import String, Integer, Boolean, Text, Date, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Per-user email settings for Gmail sync
    email_host: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, default="imap.gmail.com")
    email_user: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email_app_password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationship: user.jobs returns all jobs for this user
    jobs: Mapped[List["Job"]] = relationship("Job", back_populates="user", cascade="all, delete-orphan")

    @property
    def has_email_configured(self) -> bool:
        return bool(self.email_user and self.email_app_password)

    def __repr__(self):
        return f"<User(id={self.id}, email={self.email})>"


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    company: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="applied", index=True)
    job_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    salary_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    applied_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationship: job.user returns the user who owns this job
    user: Mapped["User"] = relationship("User", back_populates="jobs")

    def __repr__(self):
        return f"<Job(id={self.id}, company={self.company}, position={self.position})>"
