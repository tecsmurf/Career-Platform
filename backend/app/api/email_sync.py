"""
Email Integration API
=====================

    GET  /api/email/status                        connection + sync status (never credentials)
    POST /api/email/connect                       verify mailbox credentials, then store encrypted
    POST /api/email/test                          re-verify the stored connection
    POST /api/email/sync                          bounded, idempotent sync (throttled)
    POST /api/email/disconnect                    revoke credentials (jobs are never deleted)
    GET  /api/email/messages                      job-related emails (metadata)
    GET  /api/email/messages/{id}                 one email, plain text only
    GET  /api/email/suggestions                   extracted jobs awaiting review
    POST /api/email/suggestions/{id}/accept       user-approved → create/update job
    POST /api/email/suggestions/{id}/dismiss

Every endpoint: JWT-authenticated (active user) → scoped to current_user.id →
validated input → safe response. Errors use {"detail": {"code", "message"}}.
Mailbox failures never return 401 (that would log the user out of the platform).
"""
import math
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.core.config import settings
from app.core.timeutil import iso
from app.database import get_db
from app.models import EmailMessage, Job, JobSuggestion, User
from app.schemas.email import (
    ConnectionTestResponse, EmailConnectRequest, EmailDisconnectRequest, EmailMessageDetail,
    EmailMessageList, EmailStatusResponse, EmailSyncRequest, SuggestionAcceptRequest,
    SuggestionList, SuggestionOut, SyncResponse,
)
from app.schemas.job import JobCreate
from app.services.email import integration, suggestions as suggestion_service, sync as sync_service
from app.services.email.errors import EmailProviderError

router = APIRouter()


def _fail(http_status: int, code: str, message: str, headers: dict | None = None):
    raise HTTPException(status_code=http_status, detail={"code": code, "message": message}, headers=headers)


# ---------------------------------------------------------------------------
# Connection lifecycle
# ---------------------------------------------------------------------------
@router.get("/status", response_model=EmailStatusResponse)
async def get_status(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await integration.build_status(db, current_user)


@router.post("/connect", response_model=EmailStatusResponse)
async def connect_email(
    req: EmailConnectRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await integration.connect(
            db, current_user,
            provider_id=req.provider,
            email=req.email,
            password=req.password.get_secret_value(),
            host=req.host,
        )
    except integration.RateLimited as exc:
        _fail(429, "rate_limited", "Too many connection attempts. Please wait a few minutes and try again.",
              {"Retry-After": str(exc.retry_after)})
    except EmailProviderError as exc:
        _fail(exc.http_status, exc.code, exc.user_message)
    return await integration.build_status(db, current_user)


@router.post("/test", response_model=ConnectionTestResponse)
async def test_email_connection(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        ok, message, code = await integration.test_connection(db, current_user)
    except integration.NotConnected:
        _fail(409, "not_connected", "Connect your email first.")
    except integration.RateLimited as exc:
        _fail(429, "rate_limited", "Too many connection tests. Please wait a few minutes.",
              {"Retry-After": str(exc.retry_after)})
    await db.flush()
    return {"ok": ok, "message": message, "code": code, "status": await integration.build_status(db, current_user)}


@router.post("/sync", response_model=SyncResponse)
async def sync_email(
    req: EmailSyncRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    req = req or EmailSyncRequest()
    integ = await integration.get_active_integration(db, current_user.id)
    if integ is None:
        _fail(409, "not_connected", "Connect your email first.")

    # Server-side bounds always win over client input.
    days = min(req.days_back or settings.EMAIL_SYNC_DEFAULT_DAYS, settings.EMAIL_SYNC_MAX_DAYS)
    limit = min(req.max_messages or settings.EMAIL_SYNC_DEFAULT_MESSAGES, settings.EMAIL_SYNC_MAX_MESSAGES)

    try:
        await sync_service.claim_sync(db, integ)
    except sync_service.SyncBlocked as exc:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        _fail(exc.http_status, exc.code, exc.message, headers)

    try:
        summary = await sync_service.run_sync(db, current_user.id, integ, days_back=days, max_messages=limit)
    except sync_service.SyncFailed as exc:
        _fail(exc.http_status, exc.code, exc.message)
    return {"summary": summary.to_dict(), "status": await integration.build_status(db, current_user)}


@router.post("/disconnect", response_model=EmailStatusResponse)
async def disconnect_email(
    req: EmailDisconnectRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    req = req or EmailDisconnectRequest()
    await integration.disconnect(db, current_user, delete_imported_emails=req.delete_imported_emails)
    return await integration.build_status(db, current_user)


# ---------------------------------------------------------------------------
# Imported emails (job-related only)
# ---------------------------------------------------------------------------
def _message_out(m: EmailMessage, s: JobSuggestion | None, include_body: bool = False) -> dict:
    out = {
        "id": m.id,
        "sender_name": m.sender_name,
        "sender_email": m.sender_email,
        "subject": m.subject,
        "snippet": m.snippet,
        "received_at": iso(m.received_at),
        "category": m.category,
        "confidence": m.confidence,
        "classification_method": m.classification_method,
        "processing_status": m.processing_status,
        "suggestion": (
            {"id": s.id, "kind": s.kind, "review_status": s.review_status, "status": s.status} if s else None
        ),
    }
    if include_body:
        out["body_text"] = m.body_text
    return out


def _suggestion_join(user_id: int):
    return and_(JobSuggestion.email_id == EmailMessage.id, JobSuggestion.user_id == user_id)


@router.get("/messages", response_model=EmailMessageList)
async def list_messages(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
):
    where = and_(EmailMessage.user_id == current_user.id, EmailMessage.is_job_related.is_(True))
    total = (await db.execute(select(func.count(EmailMessage.id)).where(where))).scalar() or 0
    rows = (await db.execute(
        select(EmailMessage, JobSuggestion)
        .outerjoin(JobSuggestion, _suggestion_join(current_user.id))
        .where(where)
        .order_by(func.coalesce(EmailMessage.received_at, EmailMessage.created_at).desc(), EmailMessage.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )).all()
    return {
        "data": [_message_out(m, s) for m, s in rows],
        "total": total, "page": page, "limit": limit,
        "pages": math.ceil(total / limit) if total else 0,
    }


@router.get("/messages/{message_id}", response_model=EmailMessageDetail)
async def get_message(
    message_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        select(EmailMessage, JobSuggestion)
        .outerjoin(JobSuggestion, _suggestion_join(current_user.id))
        .where(
            EmailMessage.id == message_id,
            EmailMessage.user_id == current_user.id,       # ownership enforced in the query
            EmailMessage.is_job_related.is_(True),
        )
    )).first()
    if row is None:
        _fail(404, "not_found", "Email not found.")
    return _message_out(row[0], row[1], include_body=True)


# ---------------------------------------------------------------------------
# Suggestions (user review)
# ---------------------------------------------------------------------------
async def _suggestion_out(db: AsyncSession, user_id: int, s: JobSuggestion) -> dict:
    email = (await db.execute(
        select(EmailMessage).where(EmailMessage.id == s.email_id, EmailMessage.user_id == user_id)
    )).scalar_one_or_none()
    job = None
    if s.matched_job_id:
        job = (await db.execute(
            select(Job).where(Job.id == s.matched_job_id, Job.user_id == user_id)
        )).scalar_one_or_none()
    return {
        "id": s.id, "kind": s.kind, "company": s.company, "position": s.position, "status": s.status,
        "location": s.location, "salary_min": s.salary_min, "salary_max": s.salary_max,
        "job_url": s.job_url,
        "applied_date": s.applied_date.isoformat() if s.applied_date else None,
        "category": s.category, "confidence": s.confidence, "extraction_method": s.extraction_method,
        "review_status": s.review_status, "created_job_id": s.created_job_id,
        "matched_job": (
            {"id": job.id, "company": job.company, "position": job.position, "status": job.status} if job else None
        ),
        "email": (
            {"id": email.id, "subject": email.subject, "sender_name": email.sender_name,
             "sender_email": email.sender_email, "received_at": iso(email.received_at),
             "snippet": email.snippet} if email else None
        ),
        "created_at": iso(s.created_at),
    }


@router.get("/suggestions", response_model=SuggestionList)
async def list_suggestions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    review_status: Literal["pending", "accepted", "dismissed", "all"] = Query("pending"),
    limit: int = Query(20, ge=1, le=50),
):
    where = [JobSuggestion.user_id == current_user.id]
    if review_status != "all":
        where.append(JobSuggestion.review_status == review_status)
    total = (await db.execute(select(func.count(JobSuggestion.id)).where(*where))).scalar() or 0
    rows = (await db.execute(
        select(JobSuggestion).where(*where)
        .order_by(JobSuggestion.updated_at.desc(), JobSuggestion.id.desc())
        .limit(limit)
    )).scalars().all()
    return {"data": [await _suggestion_out(db, current_user.id, s) for s in rows], "total": total}


def _job_out(job: Job) -> dict:
    return {
        "id": job.id, "company": job.company, "position": job.position, "status": job.status,
        "location": job.location, "job_url": job.job_url, "salary_min": job.salary_min,
        "salary_max": job.salary_max, "notes": job.notes,
        "applied_date": job.applied_date.isoformat() if job.applied_date else None,
    }


@router.post("/suggestions/{suggestion_id}/accept")
async def accept_suggestion(
    suggestion_id: int,
    req: SuggestionAcceptRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        s = await suggestion_service.get_owned_suggestion(db, current_user.id, suggestion_id)
        if s.kind == "new_job":
            provided = req.model_dump(exclude_unset=True)
            candidate = {
                "company": provided.get("company", s.company),
                "position": provided.get("position", s.position),
                "status": provided.get("status", s.status),
                "location": provided.get("location", s.location),
                "job_url": provided.get("job_url", s.job_url),
                "salary_min": provided.get("salary_min", s.salary_min),
                "salary_max": provided.get("salary_max", s.salary_max),
                "applied_date": provided.get(
                    "applied_date", s.applied_date.isoformat() if s.applied_date else None
                ),
                "notes": provided.get("notes"),
            }
            if not (candidate["company"] or "").strip() or not (candidate["position"] or "").strip():
                _fail(422, "invalid_input", "Company and position are required before adding this job.")
            try:
                edits = JobCreate.model_validate(candidate).model_dump()
            except ValidationError as exc:
                first = exc.errors()[0] if exc.errors() else {}
                _fail(422, "invalid_input", str(first.get("msg", "Invalid job details.")).removeprefix("Value error, "))
        else:
            edits = {"status": req.status or s.status}
        s, job = await suggestion_service.accept(db, current_user.id, suggestion_id, edits)
    except suggestion_service.SuggestionError as exc:
        detail = {"code": exc.code, "message": exc.message, **exc.extra}
        raise HTTPException(status_code=exc.http_status, detail=detail)
    return {"suggestion": await _suggestion_out(db, current_user.id, s), "job": _job_out(job)}


@router.post("/suggestions/{suggestion_id}/dismiss", response_model=SuggestionOut)
async def dismiss_suggestion(
    suggestion_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        s = await suggestion_service.dismiss(db, current_user.id, suggestion_id)
    except suggestion_service.SuggestionError as exc:
        raise HTTPException(status_code=exc.http_status, detail={"code": exc.code, "message": exc.message})
    return await _suggestion_out(db, current_user.id, s)
