"""
Job Schemas — Pydantic Models for Job Application CRUD
======================================================

These schemas enforce that:
- required fields are present
- field types are correct
- field lengths are within bounds
- default values are applied

If a client sends invalid data, FastAPI automatically returns
422 Unprocessable Entity with details about what's wrong.
"""
from typing import Optional
from pydantic import BaseModel, Field


class JobCreate(BaseModel):
    """Schema for creating a new job application."""
    company: str = Field(..., min_length=1, max_length=200, examples=["Google"])
    position: str = Field(..., min_length=1, max_length=200, examples=["ML Engineer"])
    status: Optional[str] = Field("applied", examples=["applied"])
    job_url: Optional[str] = Field(None, max_length=500, examples=["https://careers.google.com/jobs/123"])
    salary_min: Optional[int] = Field(None, ge=0, examples=[100000])
    salary_max: Optional[int] = Field(None, ge=0, examples=[150000])
    location: Optional[str] = Field(None, max_length=200, examples=["Mountain View, CA"])
    notes: Optional[str] = Field(None, max_length=2000, examples=["Referral from John"])
    applied_date: Optional[str] = Field(None, examples=["2024-01-15"])


class JobUpdate(BaseModel):
    """Schema for updating a job application. All fields optional."""
    company: Optional[str] = Field(None, min_length=1, max_length=200)
    position: Optional[str] = Field(None, min_length=1, max_length=200)
    status: Optional[str] = Field(None)
    job_url: Optional[str] = Field(None, max_length=500)
    salary_min: Optional[int] = Field(None, ge=0)
    salary_max: Optional[int] = Field(None, ge=0)
    location: Optional[str] = Field(None, max_length=200)
    notes: Optional[str] = Field(None, max_length=2000)
    applied_date: Optional[str] = None


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
