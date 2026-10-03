"""
Apply Assistant endpoints — /api/apply/*
=========================================

Job intelligence and tailored applications, built into the platform:

    GET  /status                         feature + AI budget status
    GET  /overview                       counts, top matches, items to review
    GET  /profile    PUT /profile        targets, links, extra skills
    GET  /resume     PUT /resume         base resume (text); every save is a new version
    POST /resume/upload                  PDF / DOCX / TXT → text
    GET  /postings   POST /postings      list / add by link or pasted text
    GET  /postings/{id}                  analysis, fit, company research, contacts
    POST /postings/{id}/refresh          re-run against your current resume/profile
    POST /postings/{id}/track            add to your application tracker
    POST /postings/{id}/archive | /restore
    POST /postings/{id}/prepare          tailored resume + cover letter + answers (+ email)
    GET  /packages   GET /packages/{id}
    PATCH /packages/{id}                 edit (voids an approval)
    POST /packages/{id}/approve          bound to the payload hash you reviewed
    POST /packages/{id}/reject
    POST /packages/{id}/mark-sent        you sent it yourself → tracker job "applied"
    GET/POST /sources, DELETE /sources/{id}, POST /sources/{id}/run   public job boards

Nothing here sends email or submits applications. Every query is scoped to
the signed-in user; other users' records are indistinguishable from missing.
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.core.config import settings
from app.core.rate_limit import SlidingWindowLimiter
from app.database import get_db
from app.models.apply import ApplyDiscoverySource, ApplyPackage, ApplyPackageEvent, ApplyPosting
from app.services.apply import service as svc
from app.services.apply.discovery import BOARD_TOKEN_RE
from app.services.apply.llm import RequestBudget, StructuredLLM, ai_configured
from app.services.apply.resume_files import ResumeFileError, extract_resume_text

router = APIRouter()

# Per-user throttles for the expensive operations (single process — see README).
intake_limiter = SlidingWindowLimiter(max_calls=30, window_seconds=600)
prepare_limiter = SlidingWindowLimiter(max_calls=20, window_seconds=600)
upload_limiter = SlidingWindowLimiter(max_calls=10, window_seconds=600)
refresh_limiter = SlidingWindowLimiter(max_calls=40, window_seconds=600)
edit_limiter = SlidingWindowLimiter(max_calls=60, window_seconds=600)
discovery_limiter = SlidingWindowLimiter(max_calls=20, window_seconds=600)
ALL_LIMITERS = (intake_limiter, prepare_limiter, upload_limiter, refresh_limiter, edit_limiter, discovery_limiter)

_services = svc.Services()


def get_services() -> svc.Services:
    return _services


async def require_enabled() -> None:
    if not settings.APPLY_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "apply_disabled", "message": "The Apply Assistant is turned off right now."},
        )


def _throttle(limiter: SlidingWindowLimiter, user_id: int, what: str) -> None:
    retry = limiter.hit(user_id)
    if retry is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "rate_limited", "message": f"Too many {what} requests. Try again in a few minutes."},
            headers={"Retry-After": str(retry)},
        )


# ------------------------------------------------------------------ schemas --

Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
_HTTPS = re.compile(r"^https://[^\s<>\"']{3,290}$", re.I)
_PHONE = re.compile(r"^[0-9+()\-. ]{5,40}$")


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProfileIn(_In):
    headline: str | None = Field(default=None, max_length=200)
    summary: str | None = Field(default=None, max_length=3000)
    years_experience: int | None = Field(default=None, ge=0, le=60)
    target_roles: list[Short] = Field(default_factory=list, max_length=15)
    target_locations: list[Short] = Field(default_factory=list, max_length=15)
    open_to_remote: bool = True
    location: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    linkedin_url: str | None = Field(default=None, max_length=300)
    github_url: str | None = Field(default=None, max_length=300)
    portfolio_url: str | None = Field(default=None, max_length=300)
    website_url: str | None = Field(default=None, max_length=300)
    skills: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]] = Field(
        default_factory=list, max_length=60
    )

    @field_validator("linkedin_url", "github_url", "portfolio_url", "website_url")
    @classmethod
    def _https_only(cls, v: str | None) -> str | None:
        if v in (None, ""):
            return None
        if not _HTTPS.match(v):
            raise ValueError("Links must start with https://")
        return v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        if v in (None, ""):
            return None
        if not _PHONE.match(v):
            raise ValueError("Phone numbers may contain digits, spaces and + ( ) - . only")
        return v

    @field_validator("headline", "summary", "location")
    @classmethod
    def _empty_none(cls, v: str | None) -> str | None:
        return v or None


class ResumeIn(_In):
    text: str = Field(min_length=50, max_length=40_000)


class PostingIn(_In):
    url: str | None = Field(default=None, max_length=2000)
    text: str | None = Field(default=None, max_length=100_000)
    title: str | None = Field(default=None, max_length=300)
    company: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _one_source(self) -> "PostingIn":
        if not (self.url or self.text):
            raise ValueError("Paste a job link or the job description text")
        return self


class AnswerEdit(_In):
    index: int = Field(ge=0, le=50)
    answer: str = Field(max_length=4000)


class PackageEdits(_In):
    resume_text: str | None = Field(default=None, max_length=40_000)
    cover_letter: str | None = Field(default=None, max_length=8_000)
    answers: list[AnswerEdit] | None = Field(default=None, max_length=20)
    email_subject: str | None = Field(default=None, max_length=200)
    email_body: str | None = Field(default=None, max_length=8_000)


_HASH = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class PackageEditIn(_In):
    base_hash: _HASH
    edits: PackageEdits


class ApproveIn(_In):
    payload_hash: _HASH


class RejectIn(_In):
    reason: str | None = Field(default=None, max_length=500)


class MarkSentIn(_In):
    channel: Literal["company_site", "email", "other"] = "company_site"


class SourceIn(_In):
    provider: Literal["greenhouse", "lever", "ashby"]
    board_token: str = Field(min_length=1, max_length=100)
    company_name: str = Field(min_length=1, max_length=200)
    keywords: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]] = Field(
        default_factory=list, max_length=10
    )
    locations: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]] = Field(
        default_factory=list, max_length=10
    )

    @field_validator("board_token")
    @classmethod
    def _token(cls, v: str) -> str:
        v = v.strip().lower()
        if not BOARD_TOKEN_RE.match(v):
            raise ValueError("Board name may only contain lowercase letters, digits, '.', '_' and '-'")
        return v


# ------------------------------------------------------------------- status --


@router.get("/status")
async def apply_status(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    spent_today = 0.0
    if ai_configured():
        llm = StructuredLLM(db, user_id=user.id, budget=RequestBudget(max_calls=0))
        spent_today, _ = await llm.spent()
    return {
        "enabled": settings.APPLY_ENABLED,
        "ai": {
            "configured": ai_configured(),
            "daily_budget_usd": settings.APPLY_AI_DAILY_BUDGET_USD,
            "spent_today_usd": round(spent_today, 4),
        },
        "company_site_lookup": settings.APPLY_COMPANY_SITE_LOOKUP,
        "sends_anything": False,
    }


@router.get("/overview", dependencies=[Depends(require_enabled)])
async def overview(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    active = (
        await db.execute(
            select(func.count(ApplyPosting.id)).where(ApplyPosting.user_id == user.id, ApplyPosting.status != "archived")
        )
    ).scalar_one()
    by_status = dict(
        (
            await db.execute(
                select(ApplyPackage.status, func.count(ApplyPackage.id))
                .where(ApplyPackage.user_id == user.id)
                .group_by(ApplyPackage.status)
            )
        ).all()
    )
    top, _ = await svc.list_postings(db, user.id, status_filter=None, query=None, sort="fit", page=1, limit=5)
    review = (
        await db.execute(
            select(ApplyPackage)
            .where(ApplyPackage.user_id == user.id, ApplyPackage.status.in_(["ready_for_review", "approved"]))
            .order_by(ApplyPackage.updated_at.desc())
            .limit(5)
        )
    ).scalars().all()
    resume = await svc.latest_resume(db, user.id)
    profile = await svc.get_profile(db, user.id)
    return {
        "postings": active,
        "packages": {k: by_status.get(k, 0) for k in ("ready_for_review", "approved", "sent", "rejected")},
        "top_matches": [svc.serialize_posting(p) for p in top if p.fit_score is not None],
        "to_review": [svc.serialize_package(p) for p in review],
        "has_resume": resume is not None,
        "has_profile": profile is not None and bool(profile.headline),
    }


# ------------------------------------------------------------ profile/resume --


@router.get("/profile", dependencies=[Depends(require_enabled)])
async def get_profile(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return svc.serialize_profile(await svc.get_profile(db, user.id))


@router.put("/profile", dependencies=[Depends(require_enabled)])
async def put_profile(data: ProfileIn, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    profile = await svc.upsert_profile(db, user.id, data.model_dump())
    return svc.serialize_profile(profile)


def _resume_out(resume, versions) -> dict[str, Any]:
    return {
        "current": None if resume is None else {
            "id": resume.id, "version": resume.version, "text": resume.text, "filename": resume.filename,
            "created_at": svc._iso(resume.created_at),
        },
        "versions": [
            {"id": v.id, "version": v.version, "filename": v.filename, "characters": len(v.text),
             "created_at": svc._iso(v.created_at)}
            for v in versions
        ],
    }


@router.get("/resume", dependencies=[Depends(require_enabled)])
async def get_resume(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return _resume_out(await svc.latest_resume(db, user.id), await svc.list_resume_versions(db, user.id))


@router.put("/resume", dependencies=[Depends(require_enabled)])
async def put_resume(data: ResumeIn, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    resume = await svc.save_base_resume(db, user.id, data.text, None)
    return _resume_out(resume, await svc.list_resume_versions(db, user.id))


@router.post("/resume/upload", dependencies=[Depends(require_enabled)])
async def upload_resume(
    file: UploadFile = File(...), user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    _throttle(upload_limiter, user.id, "upload")
    data = await file.read(settings.APPLY_RESUME_MAX_BYTES + 1)
    try:
        text = await extract_resume_text(data, file.filename or "")
    except ResumeFileError as exc:
        raise HTTPException(status_code=422, detail={"code": "unreadable_file", "message": str(exc)}) from None
    filename = re.sub(r"[^\w.\- ()]", "_", (file.filename or "resume"))[:255]
    resume = await svc.save_base_resume(db, user.id, text, filename)
    return _resume_out(resume, await svc.list_resume_versions(db, user.id))


# ------------------------------------------------------------------ postings --


@router.get("/postings", dependencies=[Depends(require_enabled)])
async def list_postings(
    status_filter: Literal["active", "archived"] = Query("active", alias="status"),
    q: str | None = Query(None, max_length=100),
    sort: Literal["fit", "recent"] = "recent",
    page: int = Query(1, ge=1, le=1000),
    limit: int = Query(20, ge=1, le=50),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows, total = await svc.list_postings(
        db, user.id, status_filter=status_filter, query=q, sort=sort, page=page, limit=limit
    )
    return {
        "data": [svc.serialize_posting(p) for p in rows],
        "total": total, "page": page, "pages": max(1, (total + limit - 1) // limit),
    }


@router.post("/postings", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_enabled)])
async def add_posting(
    data: PostingIn,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    services: svc.Services = Depends(get_services),
):
    _throttle(intake_limiter, user.id, "posting")
    posting, created = await svc.create_posting(
        db, user, url=data.url, text=data.text, title=data.title, company=data.company, services=services
    )
    await db.flush()
    return {"created": created, "posting": svc.serialize_posting(posting, detail=True)}


@router.get("/postings/{posting_id}", dependencies=[Depends(require_enabled)])
async def get_posting(posting_id: int, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    posting = await svc.get_posting(db, user.id, posting_id)
    packages = (
        await db.execute(
            select(ApplyPackage)
            .where(ApplyPackage.posting_id == posting.id, ApplyPackage.user_id == user.id)
            .order_by(ApplyPackage.version.desc())
        )
    ).scalars().all()
    out = svc.serialize_posting(posting, detail=True)
    out["packages"] = [svc.serialize_package(p, posting=posting) for p in packages]
    return out


@router.post("/postings/{posting_id}/refresh", dependencies=[Depends(require_enabled)])
async def refresh_posting(
    posting_id: int,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    services: svc.Services = Depends(get_services),
):
    _throttle(refresh_limiter, user.id, "refresh")
    posting = await svc.get_posting(db, user.id, posting_id)
    await svc.refresh_posting(db, user, posting, services)
    return svc.serialize_posting(posting, detail=True)


@router.post("/postings/{posting_id}/track", dependencies=[Depends(require_enabled)])
async def track(posting_id: int, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    posting = await svc.get_posting(db, user.id, posting_id)
    job = await svc.track_posting(db, user, posting)
    return {"tracked_job_id": job.id, "status": job.status}


@router.post("/postings/{posting_id}/archive", dependencies=[Depends(require_enabled)])
async def archive(posting_id: int, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    posting = await svc.get_posting(db, user.id, posting_id)
    posting.status = "archived"
    return svc.serialize_posting(posting)


@router.post("/postings/{posting_id}/restore", dependencies=[Depends(require_enabled)])
async def restore(posting_id: int, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    posting = await svc.get_posting(db, user.id, posting_id)
    posting.status = "analyzed"
    return svc.serialize_posting(posting)


@router.post("/postings/{posting_id}/prepare", status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_enabled)])
async def prepare(
    posting_id: int,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    services: svc.Services = Depends(get_services),
):
    _throttle(prepare_limiter, user.id, "prepare")
    posting = await svc.get_posting(db, user.id, posting_id)
    package = await svc.prepare_package(db, user, posting, services)
    return svc.serialize_package(package, detail=True, posting=posting)


# ------------------------------------------------------------------ packages --


@router.get("/packages", dependencies=[Depends(require_enabled)])
async def list_packages(
    status_filter: Literal["open", "ready_for_review", "approved", "sent", "rejected", "all"] = Query("open", alias="status"),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ApplyPackage, ApplyPosting).join(ApplyPosting, ApplyPosting.id == ApplyPackage.posting_id).where(
        ApplyPackage.user_id == user.id
    )
    if status_filter == "open":
        stmt = stmt.where(ApplyPackage.status.in_(["ready_for_review", "approved"]))
    elif status_filter != "all":
        stmt = stmt.where(ApplyPackage.status == status_filter)
    else:
        stmt = stmt.where(ApplyPackage.status != "superseded")
    rows = (await db.execute(stmt.order_by(ApplyPackage.updated_at.desc()).limit(100))).all()
    return {"data": [svc.serialize_package(pkg, posting=posting) for pkg, posting in rows]}


@router.get("/packages/{package_id}", dependencies=[Depends(require_enabled)])
async def get_package(package_id: int, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    package = await svc.get_package(db, user.id, package_id)
    posting = await svc.get_posting(db, user.id, package.posting_id)
    events = (
        await db.execute(
            select(ApplyPackageEvent)
            .where(ApplyPackageEvent.package_id == package.id, ApplyPackageEvent.user_id == user.id)
            .order_by(ApplyPackageEvent.id)
        )
    ).scalars().all()
    out = svc.serialize_package(package, detail=True, posting=posting)
    out["posting"] = svc.serialize_posting(posting)
    out["events"] = [
        {"kind": e.kind, "payload_hash": e.payload_hash, "detail": svc._loads(e.detail, e.detail),
         "at": svc._iso(e.created_at)}
        for e in events
    ]
    return out


@router.patch("/packages/{package_id}", dependencies=[Depends(require_enabled)])
async def edit_package(
    package_id: int, data: PackageEditIn, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    _throttle(edit_limiter, user.id, "edit")
    package = await svc.get_package(db, user.id, package_id)
    edits = data.edits.model_dump(exclude_none=True)
    if "answers" in edits:
        edits["answers"] = [a for a in edits["answers"]]
    package, voided, report = await svc.edit_package(db, user, package, base_hash=data.base_hash, edits=edits)
    out = svc.serialize_package(package, detail=True)
    out["approval_voided"] = voided
    out["edit_warnings"] = [v.detail for v in report.violations] if report else []
    return out


@router.post("/packages/{package_id}/approve", dependencies=[Depends(require_enabled)])
async def approve(package_id: int, data: ApproveIn, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    package = await svc.get_package(db, user.id, package_id)
    await svc.approve_package(db, user, package, data.payload_hash)
    return svc.serialize_package(package, detail=True)


@router.post("/packages/{package_id}/reject", dependencies=[Depends(require_enabled)])
async def reject(package_id: int, data: RejectIn, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    package = await svc.get_package(db, user.id, package_id)
    await svc.reject_package(db, user, package, data.reason)
    return svc.serialize_package(package, detail=True)


@router.post("/packages/{package_id}/mark-sent", dependencies=[Depends(require_enabled)])
async def mark_sent(package_id: int, data: MarkSentIn, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    package = await svc.get_package(db, user.id, package_id)
    package, job = await svc.mark_sent(db, user, package, data.channel)
    out = svc.serialize_package(package, detail=True)
    out["tracked_job_id"] = job.id
    return out


# ------------------------------------------------------------------- sources --


async def _get_source(db: AsyncSession, user_id: int, source_id: int) -> ApplyDiscoverySource:
    source = (
        await db.execute(
            select(ApplyDiscoverySource).where(
                ApplyDiscoverySource.id == source_id, ApplyDiscoverySource.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Job board not found."})
    return source


@router.get("/sources", dependencies=[Depends(require_enabled)])
async def list_sources(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(ApplyDiscoverySource).where(ApplyDiscoverySource.user_id == user.id).order_by(ApplyDiscoverySource.id)
        )
    ).scalars().all()
    return {"data": [svc.serialize_source(s) for s in rows]}


@router.post("/sources", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_enabled)])
async def add_source(data: SourceIn, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    count = (
        await db.execute(select(func.count(ApplyDiscoverySource.id)).where(ApplyDiscoverySource.user_id == user.id))
    ).scalar_one()
    if count >= 20:
        raise HTTPException(status_code=409, detail={"code": "limit_reached", "message": "You can follow up to 20 job boards."})
    source = ApplyDiscoverySource(
        user_id=user.id, provider=data.provider, board_token=data.board_token, company_name=data.company_name,
        keywords_json=json.dumps(data.keywords), locations_json=json.dumps(data.locations),
    )
    try:
        async with db.begin_nested():
            db.add(source)
    except IntegrityError:
        raise HTTPException(
            status_code=409, detail={"code": "duplicate", "message": "You already follow that job board."}
        ) from None
    return svc.serialize_source(source)


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_enabled)])
async def delete_source(source_id: int, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    source = await _get_source(db, user.id, source_id)
    await db.delete(source)


@router.post("/sources/{source_id}/run", dependencies=[Depends(require_enabled)])
async def run_source(
    source_id: int,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    services: svc.Services = Depends(get_services),
):
    _throttle(discovery_limiter, user.id, "job board")
    source = await _get_source(db, user.id, source_id)
    result = await svc.run_discovery(db, user, source, services)
    await db.commit()  # keep last_run_at / imported postings even if the response fails to send
    return {**result, "source": svc.serialize_source(source)}
