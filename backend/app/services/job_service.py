"""
Job Service — Business Logic for Job CRUD
==========================================

All database queries for jobs go through here.
"""
from datetime import datetime, timezone, date
from typing import Optional

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job


async def create_job(
    db: AsyncSession,
    user_id: int,
    company: str,
    position: str,
    status: str = "applied",
    job_url: str = None,
    salary_min: int = None,
    salary_max: int = None,
    location: str = None,
    notes: str = None,
    applied_date: str = None,
) -> Job:
    job = Job(
        user_id=user_id,
        company=company,
        position=position,
        status=status,
        job_url=job_url,
        salary_min=salary_min,
        salary_max=salary_max,
        location=location,
        notes=notes,
        applied_date=date.fromisoformat(applied_date) if applied_date else date.today(),
    )
    db.add(job)
    await db.flush()
    await db.refresh(job)
    return job


async def get_job_by_id(db: AsyncSession, job_id: int) -> Job | None:
    result = await db.execute(select(Job).where(Job.id == job_id))
    return result.scalar_one_or_none()


async def list_jobs(
    db: AsyncSession,
    user_id: int,
    status_filter: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
) -> tuple[list[Job], int]:
    """Returns (jobs, total_count) for pagination."""
    query = select(Job).where(Job.user_id == user_id)
    count_query = select(func.count(Job.id)).where(Job.user_id == user_id)

    if status_filter:
        query = query.where(Job.status == status_filter)
        count_query = count_query.where(Job.status == status_filter)

    if search:
        search_pattern = f"%{search}%"
        search_filter = or_(
            Job.company.ilike(search_pattern),
            Job.position.ilike(search_pattern),
        )
        query = query.where(search_filter)
        count_query = count_query.where(search_filter)

    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    # Get paginated results
    query = query.order_by(Job.created_at.desc())
    query = query.offset((page - 1) * limit).limit(limit)
    result = await db.execute(query)
    jobs = list(result.scalars().all())

    return jobs, total


async def update_job(db: AsyncSession, job: Job, update_data: dict) -> Job:
    for field, value in update_data.items():
        if value is not None:
            if field == "applied_date" and isinstance(value, str):
                value = date.fromisoformat(value)
            setattr(job, field, value)
    job.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(job)
    return job


async def delete_job(db: AsyncSession, job: Job) -> None:
    await db.delete(job)
    await db.flush()


async def get_job_stats(db: AsyncSession, user_id: int) -> dict:
    """Get summary stats for dashboard."""
    result = await db.execute(
        select(Job.status, func.count(Job.id))
        .where(Job.user_id == user_id)
        .group_by(Job.status)
    )
    stats = {row[0]: row[1] for row in result.all()}
    stats["total"] = sum(stats.values())
    return stats
