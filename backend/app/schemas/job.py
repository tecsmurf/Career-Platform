"""
Job Schemas — Pydantic Models for Job Application CRUD
======================================================

These schemas enforce that:
- required fields are present
- field types are correct
- field lengths are within bounds
- status is one of the supported values
- salary_max is not less than salary_min

If a client sends invalid data, FastAPI automatically returns
422 Unprocessable Entity with details about what's wrong.
"""
from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _validate_iso_date(value: Optional[str]) -> Optional[str]:
    """Reject malformed dates with a 422 instead of crashing later with a 500."""
    if value is None or value == "":
        return None
    try:
        date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError("applied_date must be a date in YYYY-MM-DD format")
    return value


class JobStatus(str, Enum):
    """The only supported job-application statuses."""
    applied = "applied"
    interview = "interview"
    offer = "offer"
    rejected = "rejected"
    saved = "saved"


class JobCreate(BaseModel):
    """Schema for creating a new job application."""
    # use_enum_values=True → the parsed field holds the plain string value,
    # so it serialises and persists as e.g. "applied" (not "JobStatus.applied").
    model_config = ConfigDict(use_enum_values=True)

    company: str = Field(..., min_length=1, max_length=200, examples=["Google"])
    position: str = Field(..., min_length=1, max_length=200, examples=["ML Engineer"])
    status: JobStatus = Field(JobStatus.applied, examples=["applied"])
    job_url: Optional[str] = Field(None, max_length=500, examples=["https://careers.google.com/jobs/123"])
    salary_min: Optional[int] = Field(None, ge=0, examples=[100000])
    salary_max: Optional[int] = Field(None, ge=0, examples=[150000])
    location: Optional[str] = Field(None, max_length=200, examples=["Mountain View, CA"])
    notes: Optional[str] = Field(None, max_length=2000, examples=["Referral from John"])
    applied_date: Optional[str] = Field(None, examples=["2024-01-15"])

    @field_validator("applied_date")
    @classmethod
    def _check_date(cls, v):
        return _validate_iso_date(v)

    @model_validator(mode="after")
    def _check_salary(self):
        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_max < self.salary_min
        ):
            raise ValueError("salary_max must be greater than or equal to salary_min")
        return self


class JobUpdate(BaseModel):
    """Schema for updating a job application. All fields optional."""
    model_config = ConfigDict(use_enum_values=True)

    company: Optional[str] = Field(None, min_length=1, max_length=200)
    position: Optional[str] = Field(None, min_length=1, max_length=200)
    status: Optional[JobStatus] = Field(None)
    job_url: Optional[str] = Field(None, max_length=500)
    salary_min: Optional[int] = Field(None, ge=0)
    salary_max: Optional[int] = Field(None, ge=0)
    location: Optional[str] = Field(None, max_length=200)
    notes: Optional[str] = Field(None, max_length=2000)
    applied_date: Optional[str] = None

    @field_validator("applied_date")
    @classmethod
    def _check_date(cls, v):
        return _validate_iso_date(v)

    @model_validator(mode="after")
    def _check_salary(self):
        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_max < self.salary_min
        ):
            raise ValueError("salary_max must be greater than or equal to salary_min")
        return self


class JobResponse(BaseModel):
    """Schema for job data in API responses."""
    id: int
    user_id: int
    company: str
    position: str
    status: str
    job_url: Optional[str] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    location: Optional[str] = None
    notes: Optional[str] = None
    applied_date: Optional[str] = None
    created_at: str
    updated_at: str


class JobListResponse(BaseModel):
    """Schema for paginated job list response."""
    data: list[JobResponse]
    total: int
    page: int
    limit: int
    pages: int
