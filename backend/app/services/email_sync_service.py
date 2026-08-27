"""
Job Auto-Updater Service
=========================

This is the BRAIN that ties the Email MCP Server to your Job Database.

Flow:
    1. Email MCP Server → scans inbox → finds job emails → returns signals
    2. This service → matches signals to jobs in database → auto-updates status
    
    Example:
        Email: "Hi, we'd like to schedule a technical interview for the ML Engineer role"
        Signal: {status: "interviewing", company: "Google"}
        Match: finds "Google - ML Engineer" in your jobs table
        Action: UPDATE jobs SET status = 'interviewing' WHERE id = 42

    The matching uses:
    - Exact company name match
    - Fuzzy company name match (handles "Google LLC" vs "Google")
    - Position keyword matching from email body
    - AI-powered matching for ambiguous cases (OpenAI)
"""
import json
import re
from datetime import datetime, timezone

from openai import AsyncOpenAI
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Job
from app.core.config import settings

client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


async def match_email_to_job(
    db: AsyncSession,
    user_id: int,
    detected_company: str | None,
    email_subject: str,
    email_body: str,
    detected_status: str,
) -> dict | None:
    """
    Try to match a job email to an existing job in the database.
    
    Strategy:
    1. If we have a company name → search by company
    2. If multiple matches → use position keywords to narrow down
    3. If still ambiguous → use AI to pick the best match
    """
    if not detected_company:
        return None
    
    # Step 1: Find jobs by company name (fuzzy match)
    company_lower = detected_company.lower().strip()
    result = await db.execute(
        select(Job).where(
            Job.user_id == user_id,
            Job.company.ilike(f"%{company_lower}%"),
        )
    )
    matching_jobs = list(result.scalars().all())
    
    if not matching_jobs:
        # Try splitting company name for partial matches
        parts = company_lower.split()
        for part in parts:
            if len(part) > 3:  # Skip short words
                result = await db.execute(
                    select(Job).where(
                        Job.user_id == user_id,
                        Job.company.ilike(f"%{part}%"),
                    )
                )
                matching_jobs = list(result.scalars().all())
                if matching_jobs:
                    break
    
    if not matching_jobs:
        return None
    
    # Step 2: If exactly one match, we're done
    if len(matching_jobs) == 1:
        return {
            "job": matching_jobs[0],
            "match_method": "company_name",
            "confidence": "high",
        }
    
    # Step 3: Multiple matches — use AI to pick the best one
    return await _ai_match(matching_jobs, email_subject, email_body, detected_company)


async def _ai_match(
    candidate_jobs: list[Job],
    email_subject: str,
    email_body: str,
    detected_company: str,
) -> dict | None:
    """Use AI to match an email to the most relevant job."""
    jobs_desc = "\n".join([
        f"Job ID {j.id}: {j.company} - {j.position} (status: {j.status})"
        for j in candidate_jobs
    ])
    
    prompt = f"""Match this job email to one of the candidate jobs.

Email subject: {email_subject}
Email body (first 500 chars): {email_body[:500]}
Detected company: {detected_company}

Candidate jobs:
{jobs_desc}

Return ONLY the Job ID number of the best match, or "none" if no good match.
Response format: just the number or "none", nothing else."""

    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=10,
    )
    
    answer = response.choices[0].message.content.strip().lower()
    
    if answer == "none":
        return None
    
    try:
        job_id = int(re.search(r'\d+', answer).group())
        matched = next((j for j in candidate_jobs if j.id == job_id), None)
        if matched:
            return {
                "job": matched,
                "match_method": "ai_match",
                "confidence": "medium",
            }
    except (ValueError, AttributeError):
        pass
    
    return None


async def auto_update_jobs_from_emails(
    db: AsyncSession,
    user_id: int,
    job_emails: list[dict],
) -> list[dict]:
    """
    Process job email signals and auto-update job statuses.
    
    Args:
        db: Database session
        user_id: The user who owns the jobs
        job_emails: List of detected job emails from Email MCP Server
        
    Returns:
        List of updates made: [{job_id, company, old_status, new_status, email_subject}]
    """
    updates = []
    
    # Status progression — only update if it's a forward progression
    STATUS_ORDER = {
        "applied": 1,
        "interviewing": 2,
        "offer": 3,
        "rejected": 99,  # Terminal state
        "withdrawn": 99,  # Terminal state
    }
    
    for email_data in job_emails:
        signal = email_data.get("job_signal", {})
        detected_status = signal.get("detected_status")
        detected_company = email_data.get("detected_company")
        confidence = signal.get("confidence", "low")
        
        if detected_status in ("unknown", None) or confidence == "low":
            continue
        
        # Try to match to a job
        match = await match_email_to_job(
            db, user_id,
            detected_company=detected_company,
            email_subject=email_data.get("subject", ""),
            email_body=email_data.get("body_preview", ""),
            detected_status=detected_status,
        )
        
        if not match:
            continue
        
        job = match["job"]
        old_status = job.status
        new_status = detected_status
        
        # Only update if it's a forward progression (don't go backwards)
        old_order = STATUS_ORDER.get(old_status, 0)
        new_order = STATUS_ORDER.get(new_status, 0)
        
        if new_order > old_order:
            job.status = new_status
            job.updated_at = datetime.now(timezone.utc)
            
            # Add note about the auto-update
            auto_note = f"[Auto-updated from email] {email_data.get('subject', '')[:100]}"
            if job.notes:
                job.notes = f"{job.notes}\n{auto_note}"
            else:
                job.notes = auto_note
            
            await db.flush()
            
            updates.append({
                "job_id": job.id,
                "company": job.company,
                "position": job.position,
                "old_status": old_status,
                "new_status": new_status,
                "email_subject": email_data.get("subject", ""),
                "match_method": match["match_method"],
                "confidence": match["confidence"],
            })
    
    return updates
