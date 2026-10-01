"""
Job suggestions — the human-in-the-loop step between email detection and jobs.
==============================================================================

- A suggestion is created for each actionable job email, OR merged into an
  existing pending suggestion for the same opportunity (one card per job, the
  most advanced stage wins).
- `new_job` suggestions propose a job; `status_update` suggestions propose a
  status change for one of the user's existing jobs. Backward moves are never
  proposed.
- Nothing here touches the jobs table except accept(), which only runs on an
  explicit user action and is atomic (double-submits cannot create two jobs).
- Every query is scoped by user_id.
"""
from datetime import date

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import utcnow
from app.models import EmailMessage, Job, JobSuggestion
from app.services.email.classifier import STATUS_STAGE, Classification, normalize_company


class SuggestionError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 409, **extra):
        self.code, self.message, self.http_status, self.extra = code, message, http_status, extra
        super().__init__(message)


def _norm_position(p: str | None) -> str:
    return " ".join((p or "").casefold().split())


def _positions_compatible(a: str | None, b: str | None) -> bool:
    return not a or not b or _norm_position(a) == _norm_position(b)


async def _find_matching_job(db: AsyncSession, user_id: int, company: str | None, position: str | None) -> Job | None:
    key = normalize_company(company)
    if not key:
        return None
    rows = (await db.execute(select(Job).where(Job.user_id == user_id))).scalars().all()
    same_company = [j for j in rows if normalize_company(j.company) == key]
    if not same_company:
        return None
    if position:
        exact = [j for j in same_company if _norm_position(j.position) == _norm_position(position)]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            return None
    return same_company[0] if len(same_company) == 1 else None


async def _find_pending_for_opportunity(db, user_id, kind, company, position, matched_job_id):
    q = select(JobSuggestion).where(
        JobSuggestion.user_id == user_id,
        JobSuggestion.review_status == "pending",
        JobSuggestion.kind == kind,
    )
    if kind == "status_update":
        q = q.where(JobSuggestion.matched_job_id == matched_job_id)
        return (await db.execute(q)).scalars().first()
    key = normalize_company(company)
    if not key:
        return None
    for s in (await db.execute(q)).scalars().all():
        if normalize_company(s.company) == key and _positions_compatible(s.position, position):
            return s
    return None


def _fill_blanks(target: JobSuggestion, c: Classification) -> None:
    for attr in ("company", "position", "location", "job_url"):
        if getattr(target, attr) is None and getattr(c, attr):
            setattr(target, attr, getattr(c, attr)[:500 if attr == "job_url" else 200])
    if target.salary_min is None and c.salary_min is not None:
        target.salary_min, target.salary_max = c.salary_min, c.salary_max
    if target.applied_date is None and c.applied_date is not None:
        target.applied_date = c.applied_date


async def record_suggestion(db: AsyncSession, user_id: int, email: EmailMessage, c: Classification) -> str | None:
    """Create or merge a suggestion. Returns 'created', 'merged' or None (nothing to suggest)."""
    status = c.status
    if not c.is_actionable or status is None:
        return None

    job = await _find_matching_job(db, user_id, c.company, c.position)
    if job is not None:
        if STATUS_STAGE.get(status, 0) <= STATUS_STAGE.get(job.status, 0):
            return None                       # never propose moving a job backwards / sideways
        kind, matched_job_id = "status_update", job.id
    else:
        kind, matched_job_id = "new_job", None

    existing = await _find_pending_for_opportunity(db, user_id, kind, c.company, c.position, matched_job_id)
    if existing is not None:
        if STATUS_STAGE.get(status, 0) >= STATUS_STAGE.get(existing.status, 0):
            existing.status = status
            existing.category = c.category
            existing.confidence = c.confidence
            existing.extraction_method = c.method
            existing.email_id = email.id       # point at the newest evidence
        _fill_blanks(existing, c)
        existing.updated_at = utcnow()
        return "merged"

    db.add(JobSuggestion(
        user_id=user_id,
        email_id=email.id,
        kind=kind,
        matched_job_id=matched_job_id,
        company=(c.company or None) and c.company[:200],
        position=(c.position or None) and c.position[:200],
        status=status,
        location=(c.location or None) and c.location[:200],
        salary_min=c.salary_min,
        salary_max=c.salary_max,
        job_url=(c.job_url or None) and c.job_url[:500],
        applied_date=c.applied_date,
        category=c.category,
        confidence=c.confidence,
        extraction_method=c.method,
        review_status="pending",
    ))
    return "created"


async def get_owned_suggestion(db: AsyncSession, user_id: int, suggestion_id: int) -> JobSuggestion:
    s = (await db.execute(
        select(JobSuggestion).where(JobSuggestion.id == suggestion_id, JobSuggestion.user_id == user_id)
    )).scalar_one_or_none()
    if s is None:
        raise SuggestionError("not_found", "Suggestion not found.", 404)
    return s


async def _claim(db: AsyncSession, user_id: int, suggestion_id: int, new_state: str) -> bool:
    """Atomically move pending → new_state. False if it was already reviewed."""
    res = await db.execute(
        update(JobSuggestion)
        .where(
            JobSuggestion.id == suggestion_id,
            JobSuggestion.user_id == user_id,
            JobSuggestion.review_status == "pending",
        )
        .values(review_status=new_state, reviewed_at=utcnow(), updated_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    return res.rowcount == 1


async def dismiss(db: AsyncSession, user_id: int, suggestion_id: int) -> JobSuggestion:
    s = await get_owned_suggestion(db, user_id, suggestion_id)
    if not await _claim(db, user_id, suggestion_id, "dismissed"):
        raise SuggestionError("already_reviewed", "This suggestion was already reviewed.")
    await db.refresh(s)
    return s


def _source_note(email: EmailMessage | None) -> str:
    if email is None:
        return "Source: email"
    when = email.received_at.date().isoformat() if email.received_at else "unknown date"
    subject = (email.subject or "(no subject)")[:120]
    return f"Source: email “{subject}” ({when})"


async def accept(db: AsyncSession, user_id: int, suggestion_id: int, edits: dict) -> tuple[JobSuggestion, Job]:
    """Apply a suggestion with the user's (validated) edits. Explicit user action only."""
    s = await get_owned_suggestion(db, user_id, suggestion_id)
    if s.review_status != "pending":
        raise SuggestionError("already_reviewed", "This suggestion was already reviewed.")

    email = (await db.execute(
        select(EmailMessage).where(EmailMessage.id == s.email_id, EmailMessage.user_id == user_id)
    )).scalar_one_or_none()

    if s.kind == "status_update":
        job = None
        if s.matched_job_id is not None:
            job = (await db.execute(
                select(Job).where(Job.id == s.matched_job_id, Job.user_id == user_id)
            )).scalar_one_or_none()
        if job is None:
            raise SuggestionError("job_missing", "The job this update refers to no longer exists. Dismiss it instead.")
        new_status = edits.get("status") or s.status
        if not await _claim(db, user_id, suggestion_id, "accepted"):
            raise SuggestionError("already_reviewed", "This suggestion was already reviewed.")
        job.status = new_status
        job.updated_at = utcnow()
        await db.flush()
        await db.refresh(s)
        return s, job

    # new_job — edits were validated with the JobCreate schema by the API layer.
    company, position = edits["company"], edits["position"]
    dup = (await db.execute(
        select(Job.id).where(
            Job.user_id == user_id,
            func.lower(Job.company) == company.strip().lower(),
            func.lower(Job.position) == position.strip().lower(),
        )
    )).scalar_one_or_none()
    if dup is not None:
        raise SuggestionError("duplicate_job", "You're already tracking this job.", job_id=dup)

    if not await _claim(db, user_id, suggestion_id, "accepted"):
        raise SuggestionError("already_reviewed", "This suggestion was already reviewed.")

    note = _source_note(email)
    notes = edits.get("notes")
    notes = f"{notes}\n\n{note}" if notes else note
    applied = edits.get("applied_date")
    job = Job(
        user_id=user_id,
        company=company.strip(),
        position=position.strip(),
        status=edits.get("status") or s.status,
        job_url=edits.get("job_url"),
        salary_min=edits.get("salary_min"),
        salary_max=edits.get("salary_max"),
        location=edits.get("location"),
        notes=notes[:2000],
        applied_date=date.fromisoformat(applied) if isinstance(applied, str) and applied else (applied or date.today()),
    )
    db.add(job)
    await db.flush()
    s.created_job_id = job.id
    await db.flush()
    await db.refresh(s)
    await db.refresh(job)
    return s, job
