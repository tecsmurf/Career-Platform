"""
Jobs CRUD Endpoints — Now with PostgreSQL
==========================================

    POST   /api/jobs         → Create job
    GET    /api/jobs         → List jobs (filter, search, paginate)
    GET    /api/jobs/stats   → Dashboard stats
    GET    /api/jobs/{id}    → Get one job
    PUT    /api/jobs/{id}    → Update job
    DELETE /api/jobs/{id}    → Delete job
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models import User, Job
from app.schemas.job import JobCreate, JobUpdate, JobResponse, JobListResponse
from app.services import job_service

router = APIRouter()


def _job_to_response(job: Job) -> dict:
    """Convert a Job ORM object to a response dict."""
    return {
        "id": job.id,
        "user_id": job.user_id,
        "company": job.company,
        "position": job.position,
        "status": job.status,
        "job_url": job.job_url,
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "location": job.location,
        "notes": job.notes,
        "applied_date": job.applied_date.isoformat() if job.applied_date else None,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    job_data: JobCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new job application."""
    job = await job_service.create_job(
        db,
        user_id=current_user.id,
        company=job_data.company,
        position=job_data.position,
        status=job_data.status or "applied",
        job_url=job_data.job_url,
        salary_min=job_data.salary_min,
        salary_max=job_data.salary_max,
        location=job_data.location,
        notes=job_data.notes,
        applied_date=job_data.applied_date,
    )
    return _job_to_response(job)


@router.get("", response_model=JobListResponse)
async def list_jobs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    status: Optional[str] = Query(None, description="Filter by status"),
    search: Optional[str] = Query(None, description="Search company or position"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    """List job applications with optional filters and pagination."""
    jobs, total = await job_service.list_jobs(
        db,
        user_id=current_user.id,
        status_filter=status,
        search=search,
        page=page,
        limit=limit,
    )
    return {
        "data": [_job_to_response(j) for j in jobs],
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit if total > 0 else 0,
    }


@router.get("/stats")
async def get_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get job application statistics for the dashboard."""
    return await job_service.get_job_stats(db, current_user.id)


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific job application."""
    job = await job_service.get_job_by_id(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    return _job_to_response(job)


@router.put("/{job_id}", response_model=JobResponse)
async def update_job(
    job_id: int,
    job_data: JobUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a job application."""
    job = await job_service.get_job_by_id(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    update_data = job_data.model_dump(exclude_unset=True)
    job = await job_service.update_job(db, job, update_data)
    return _job_to_response(job)


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a job application."""
    job = await job_service.get_job_by_id(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    await job_service.delete_job(db, job)
