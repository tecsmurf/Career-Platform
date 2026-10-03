"""
Apply Assistant — business logic.

Every function takes the acting user's id and filters every query by it:
another user's posting, package or source is simply "not found" (404).

Pipeline for one posting (all deterministic unless AI is configured):
    intake (text, or https link → SafeFetcher) → analyze_posting → injection scan
    → dedup (content hash) → match against the user's profile + base resume
    → company research (posting facts + employer homepage title/description)

Preparing an application:
    tailor resume (re-order only) → cover letter / answers / outreach email
    → fabrication guard on every document → package (payload + sha256)
    → review: edit (voids approval) / approve (bound to the hash) / reject
    → approved = frozen copy-ready version; the user sends it and marks it sent
    → the tracker job moves to "applied".
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Job, User
from app.models.apply import (
    ApplyDiscoverySource, ApplyPackage, ApplyPackageEvent, ApplyPosting, ApplyProfile, ApplyResume,
)
from app.services.apply import guard
from app.services.apply.candidate import CandidateFacts, build_candidate_facts
from app.services.apply.discovery import (
    DiscoveryError, DiscoveryProvider, fetch_board, matches_filters,
)
from app.services.apply.documents import generate_documents
from app.services.apply.extract import analyze_posting, html_to_text, looks_like_html, normalize_text
from app.services.apply.fetcher import FetchError, SafeFetcher
from app.services.apply.injection import scan
from app.services.apply.llm import LLMUnavailable, RequestBudget, StructuredLLM, ai_configured
from app.services.apply.match import match
from app.services.apply.research import research_company
from app.services.apply.schemas import (
    CompanyResearch, GuardReport, JDAnalysis, LLMRoleSummary, MatchResult,
)
from app.services.apply.tailor import tailor_resume

UNTITLED = "Untitled role"
UNKNOWN_COMPANY = "Unknown company"
_EDITABLE = {"resume_text", "cover_letter", "answers", "email_subject", "email_body"}
_LIMITS = {"resume_text": 40_000, "cover_letter": 8_000, "email_subject": 200, "email_body": 8_000}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _err(code: int, error: str, message: str) -> HTTPException:
    return HTTPException(status_code=code, detail={"code": error, "message": message})


def _loads(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except ValueError:
        return default


def canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def plain_text(raw: str) -> str:
    """The text an analysis is computed from (HTML → text, whitespace normalised)."""
    return html_to_text(raw)[0] if looks_like_html(raw) else normalize_text(raw)


def content_hash(text: str) -> str:
    return sha256_hex(" ".join(normalize_text(text).lower().split()))


# --------------------------------------------------------------- profile --


async def get_profile(db: AsyncSession, user_id: int) -> ApplyProfile | None:
    return (await db.execute(select(ApplyProfile).where(ApplyProfile.user_id == user_id))).scalar_one_or_none()


async def upsert_profile(db: AsyncSession, user_id: int, data: dict[str, Any]) -> ApplyProfile:
    profile = await get_profile(db, user_id)
    if profile is None:
        profile = ApplyProfile(user_id=user_id)
        db.add(profile)
    for key, value in data.items():
        if key in {"target_roles", "target_locations", "skills"}:
            setattr(profile, f"{key}_json", json.dumps(value or []))
        else:
            setattr(profile, key, value)
    await db.flush()
    return profile


def serialize_profile(profile: ApplyProfile | None) -> dict[str, Any]:
    if profile is None:
        return {
            "headline": None, "summary": None, "years_experience": None, "target_roles": [],
            "target_locations": [], "open_to_remote": True, "location": None, "phone": None,
            "linkedin_url": None, "github_url": None, "portfolio_url": None, "website_url": None,
            "skills": [],
        }
    return {
        "headline": profile.headline,
        "summary": profile.summary,
        "years_experience": profile.years_experience,
        "target_roles": _loads(profile.target_roles_json, []),
        "target_locations": _loads(profile.target_locations_json, []),
        "open_to_remote": profile.open_to_remote,
        "location": profile.location,
        "phone": profile.phone,
        "linkedin_url": profile.linkedin_url,
        "github_url": profile.github_url,
        "portfolio_url": profile.portfolio_url,
        "website_url": profile.website_url,
        "skills": _loads(profile.skills_json, []),
    }


# ---------------------------------------------------------------- resume --


async def latest_resume(db: AsyncSession, user_id: int, kind: str = "base") -> ApplyResume | None:
    return (
        await db.execute(
            select(ApplyResume)
            .where(ApplyResume.user_id == user_id, ApplyResume.kind == kind)
            .order_by(ApplyResume.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _next_resume_version(db: AsyncSession, user_id: int, kind: str) -> int:
    current = (
        await db.execute(
            select(func.max(ApplyResume.version)).where(ApplyResume.user_id == user_id, ApplyResume.kind == kind)
        )
    ).scalar_one()
    return int(current or 0) + 1


async def save_base_resume(db: AsyncSession, user_id: int, text: str, filename: str | None) -> ApplyResume:
    """Every save is a new version; older versions (and tailored copies) are kept."""
    text = text.strip()
    latest = await latest_resume(db, user_id)
    if latest is not None and latest.text == text:
        return latest
    resume = ApplyResume(
        user_id=user_id, kind="base", version=await _next_resume_version(db, user_id, "base"),
        text=text, filename=(filename or None) and filename[:255],
    )
    db.add(resume)
    await db.flush()
    return resume


async def list_resume_versions(db: AsyncSession, user_id: int) -> list[ApplyResume]:
    return list(
        (
            await db.execute(
                select(ApplyResume)
                .where(ApplyResume.user_id == user_id, ApplyResume.kind == "base")
                .order_by(ApplyResume.version.desc())
                .limit(20)
            )
        ).scalars()
    )


async def candidate_facts(db: AsyncSession, user: User) -> CandidateFacts:
    profile = await get_profile(db, user.id)
    resume = await latest_resume(db, user.id)
    return build_candidate_facts(
        user_id=user.id,
        full_name=user.full_name,
        email=user.email,
        profile=profile,
        resume_text=resume.text if resume else None,
        resume_version_id=resume.id if resume else None,
    )


# --------------------------------------------------------------- posting --


@dataclass
class Services:
    """Injectable collaborators (tests swap in fakes)."""

    fetcher: SafeFetcher | None = None
    llm_client: Any | None = None

    def get_fetcher(self) -> SafeFetcher:
        if self.fetcher is None:
            self.fetcher = SafeFetcher()
        return self.fetcher


async def get_posting(db: AsyncSession, user_id: int, posting_id: int) -> ApplyPosting:
    posting = (
        await db.execute(
            select(ApplyPosting).where(ApplyPosting.id == posting_id, ApplyPosting.user_id == user_id)
        )
    ).scalar_one_or_none()
    if posting is None:
        raise _err(404, "not_found", "Posting not found.")
    return posting


def _company_text(research: CompanyResearch | None) -> str:
    if research is None:
        return ""
    return "\n".join(f"{f.value} {f.excerpt}" for f in research.verified_facts)


async def _apply_analysis(
    db: AsyncSession,
    user: User,
    posting: ApplyPosting,
    *,
    services: Services,
    facts: CandidateFacts | None = None,
    research: bool = True,
    site_lookup: bool = True,
) -> None:
    """(Re)compute analysis, match and research for one posting, in place.

    ``site_lookup=False`` builds company research from the posting alone (no
    outbound request) — used for bulk board imports.
    """
    title_hint = posting.title if posting.title and posting.title != UNTITLED else None
    company_hint = posting.company if posting.company and posting.company != UNKNOWN_COMPANY else None
    analysis, text, hidden = analyze_posting(posting.raw_text, title_hint=title_hint, company_hint=company_hint)

    findings = [{"kind": f.kind, "excerpt": f.excerpt} for f in scan(text)]
    for snippet in hidden[:5]:
        findings.append({"kind": "hidden_text", "excerpt": snippet[:200]})
        for f in scan(snippet):
            findings.append({"kind": f.kind, "excerpt": f.excerpt})

    posting.raw_text = text
    posting.title = (analysis.title or posting.title or UNTITLED)[:300]
    posting.company = (analysis.company or posting.company or UNKNOWN_COMPANY)[:300]
    posting.location = (analysis.location or posting.location)
    posting.location_type = analysis.location_type
    posting.analysis_json = analysis.model_dump_json()
    posting.injection_json = json.dumps(findings[:15]) if findings else None

    facts = facts or await candidate_facts(db, user)
    result = match(analysis, facts)
    posting.match_json = result.model_dump_json()
    posting.fit_score = None if result.recommendation == "needs_profile" else result.score

    if research:
        allow_fetch = settings.APPLY_COMPANY_SITE_LOOKUP and site_lookup
        company = await research_company(
            jd=analysis, job_text=text, listing_url=posting.listing_url, apply_url=posting.apply_url,
            fetcher=services.get_fetcher() if allow_fetch else None, allow_fetch=allow_fetch,
        )
        if site_lookup and not findings and (ai_configured() or services.llm_client is not None):
            company = await _ai_role_summary(db, user, company, analysis, text, facts, services)
        posting.research_json = company.model_dump_json()
    posting.analyzed_at = _now()
    posting.status = "analyzed" if posting.status != "archived" else posting.status


async def _ai_role_summary(
    db: AsyncSession, user: User, company: CompanyResearch, analysis: JDAnalysis, text: str,
    facts: CandidateFacts, services: Services,
) -> CompanyResearch:
    llm = StructuredLLM(db, user_id=user.id, budget=RequestBudget(max_calls=1), client=services.llm_client)
    try:
        summary = await llm.generate(
            feature="role_summary",
            schema=LLMRoleSummary,
            instructions=(
                "Summarise what this role is about and what the employer appears to value, in 2-3 neutral "
                "sentences, using only the posting. Return {\"summary\": \"...\", \"themes\": [...]}"
            ),
            data={
                "title": analysis.title, "company": analysis.company,
                "responsibilities": analysis.responsibilities[:12],
                "requirements": analysis.qualifications[:12],
                "about": analysis.about_company,
            },
        )
    except LLMUnavailable as exc:
        company.notes.append(f"AI summary skipped: {exc.reason}")
        return company
    report = guard.check(summary.summary, facts=facts, job_text=text)
    if not report.ok:
        company.notes.append("AI summary discarded: it mentioned details that are not in the posting")
        return company
    company.interpretation = [f"AI summary: {summary.summary}", *company.interpretation][:10]
    return company


async def active_posting_count(db: AsyncSession, user_id: int) -> int:
    return int((
        await db.execute(
            select(func.count(ApplyPosting.id)).where(ApplyPosting.user_id == user_id, ApplyPosting.status != "archived")
        )
    ).scalar_one())


async def analyse_or_422(db: AsyncSession, user: User, posting: ApplyPosting, services: Services, **kwargs: Any) -> None:
    try:
        await _apply_analysis(db, user, posting, services=services, **kwargs)
    except ValidationError:
        raise _err(422, "unreadable_posting", "That posting couldn't be analysed. Paste the job description text instead.") from None


async def create_posting(
    db: AsyncSession,
    user: User,
    *,
    url: str | None,
    text: str | None,
    title: str | None,
    company: str | None,
    services: Services,
) -> tuple[ApplyPosting, bool]:
    """Returns (posting, created). An identical posting already tracked is returned as-is."""
    if await active_posting_count(db, user.id) >= settings.APPLY_MAX_POSTINGS_PER_USER:
        raise _err(409, "limit_reached", "You have reached the maximum number of saved postings. Archive some first.")

    listing_url = None
    raw = (text or "").strip()
    if url:
        if not raw:
            try:
                page = await services.get_fetcher().get(url)
            except FetchError as exc:
                raise _err(422, "fetch_failed", f"Couldn't read that link: {exc} You can paste the posting text instead.") from None
            raw = page.text
            listing_url = page.final_url
        else:
            from app.services.apply.fetcher import validate_url

            try:
                listing_url, _ = validate_url(url)
            except FetchError as exc:
                raise _err(422, "invalid_url", str(exc)) from None
        if listing_url:
            existing = (
                await db.execute(
                    select(ApplyPosting).where(
                        ApplyPosting.user_id == user.id, ApplyPosting.listing_url == listing_url
                    )
                )
            ).scalars().first()
            if existing is not None:
                return existing, False

    text_only = plain_text(raw[:200_000])
    if len(text_only.split()) < 30:
        raise _err(422, "too_short", "That posting has too little text to analyse. Paste the full job description.")
    digest = content_hash(text_only)
    dup = (
        await db.execute(
            select(ApplyPosting).where(ApplyPosting.user_id == user.id, ApplyPosting.content_hash == digest)
        )
    ).scalar_one_or_none()
    if dup is not None:
        return dup, False

    posting = ApplyPosting(
        user_id=user.id,
        source_type="url" if url else "manual",
        listing_url=listing_url,
        apply_url=listing_url,
        title=(title or UNTITLED).strip()[:300] or UNTITLED,
        company=(company or UNKNOWN_COMPANY).strip()[:300] or UNKNOWN_COMPANY,
        raw_text=raw[:200_000],
        content_hash=digest,
        status="analyzed",
    )
    await analyse_or_422(db, user, posting, services)
    dup = (
        await db.execute(
            select(ApplyPosting).where(
                ApplyPosting.user_id == user.id, ApplyPosting.content_hash == posting.content_hash
            )
        )
    ).scalar_one_or_none()
    if dup is not None:
        return dup, False
    try:
        async with db.begin_nested():
            db.add(posting)
    except IntegrityError:
        dup = (
            await db.execute(
                select(ApplyPosting).where(
                    ApplyPosting.user_id == user.id, ApplyPosting.content_hash == posting.content_hash
                )
            )
        ).scalar_one()
        return dup, False
    return posting, True


async def list_postings(
    db: AsyncSession, user_id: int, *, status_filter: str | None, query: str | None, sort: str,
    page: int, limit: int,
) -> tuple[list[ApplyPosting], int]:
    stmt = select(ApplyPosting).where(ApplyPosting.user_id == user_id)
    if status_filter == "archived":
        stmt = stmt.where(ApplyPosting.status == "archived")
    else:
        stmt = stmt.where(ApplyPosting.status != "archived")
    if query:
        like = f"%{query.lower()}%"
        stmt = stmt.where(
            func.lower(ApplyPosting.title).like(like) | func.lower(ApplyPosting.company).like(like)
        )
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    if sort == "fit":
        stmt = stmt.order_by(ApplyPosting.fit_score.is_(None), ApplyPosting.fit_score.desc(), ApplyPosting.id.desc())
    else:
        stmt = stmt.order_by(ApplyPosting.created_at.desc(), ApplyPosting.id.desc())
    rows = (await db.execute(stmt.offset((page - 1) * limit).limit(limit))).scalars().all()
    return list(rows), int(total)


async def refresh_posting(db: AsyncSession, user: User, posting: ApplyPosting, services: Services) -> ApplyPosting:
    await analyse_or_422(db, user, posting, services)
    await db.flush()
    return posting


async def track_posting(db: AsyncSession, user: User, posting: ApplyPosting, *, status_value: str = "saved") -> Job:
    """Add the posting to the user's application tracker (once)."""
    if posting.tracked_job_id is not None:
        job = (
            await db.execute(select(Job).where(Job.id == posting.tracked_job_id, Job.user_id == user.id))
        ).scalar_one_or_none()
        if job is not None:
            return job
    analysis = JDAnalysis.model_validate_json(posting.analysis_json) if posting.analysis_json else None
    salary = analysis.salary if analysis and analysis.salary and analysis.salary.period == "year" else None
    job = Job(
        user_id=user.id,
        company=posting.company[:255],
        position=posting.title[:255],
        status=status_value,
        job_url=(posting.listing_url or posting.apply_url or None) and (posting.listing_url or posting.apply_url)[:500],
        location=(posting.location or None) and posting.location[:255],
        salary_min=salary.min if salary else None,
        salary_max=salary.max if salary else None,
        notes="Added from Apply Assistant",
        applied_date=date.today() if status_value == "applied" else None,
    )
    db.add(job)
    await db.flush()
    posting.tracked_job_id = job.id
    return job


# ------------------------------------------------------------- discovery --


async def run_discovery(
    db: AsyncSession, user: User, source: ApplyDiscoverySource, services: Services
) -> dict[str, Any]:
    last = source.last_run_at
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    if last is not None and _now() - last < timedelta(seconds=settings.APPLY_DISCOVERY_COOLDOWN_SECONDS):
        wait = settings.APPLY_DISCOVERY_COOLDOWN_SECONDS - int((_now() - last).total_seconds())
        raise HTTPException(
            status_code=429,
            detail={"code": "cooldown", "message": f"This board was checked recently. Try again in {max(1, wait // 60)} min."},
            headers={"Retry-After": str(max(1, wait))},
        )
    provider = DiscoveryProvider(source.provider)
    source.last_run_at = _now()
    try:
        postings = await fetch_board(provider, source.board_token, services.get_fetcher())
    except DiscoveryError as exc:
        source.last_status = str(exc)[:300]
        source.last_new_count = 0
        # Commit before raising: the failed run must still start the cooldown
        # (otherwise errors could be retried in a tight loop against the board).
        await db.commit()
        raise _err(502, "discovery_failed", str(exc)) from None

    keywords = _loads(source.keywords_json, [])
    locations = _loads(source.locations_json, [])
    matched = [p for p in postings if matches_filters(p, keywords, locations)]
    facts = await candidate_facts(db, user)
    new_ids: list[int] = []
    skipped = 0
    unreadable = 0
    room = settings.APPLY_MAX_POSTINGS_PER_USER - await active_posting_count(db, user.id)
    for item in matched:
        if len(new_ids) >= min(settings.APPLY_DISCOVERY_MAX_NEW, max(0, room)):
            break
        exists = (
            await db.execute(
                select(ApplyPosting.id).where(
                    ApplyPosting.user_id == user.id,
                    ApplyPosting.source_type == provider.value,
                    ApplyPosting.source_job_id == item.source_job_id,
                )
            )
        ).scalar_one_or_none()
        if exists is not None:
            skipped += 1
            continue
        posting = ApplyPosting(
            user_id=user.id,
            source_type=provider.value,
            source_job_id=item.source_job_id,
            discovery_source_id=source.id,
            listing_url=item.listing_url,
            apply_url=item.apply_url,
            title=item.title[:300],
            company=source.company_name[:300],
            location=item.location,
            raw_text=(item.description or item.title)[:200_000],
            posted_at=item.posted_at,
            status="analyzed",
        )
        # Board postings are analysed, matched and researched from the posting
        # itself — no per-posting outbound requests (a run makes exactly one).
        try:
            await _apply_analysis(db, user, posting, services=services, facts=facts, site_lookup=False)
        except ValidationError:
            unreadable += 1
            continue
        posting.content_hash = content_hash(posting.raw_text)
        if (
            await db.execute(
                select(ApplyPosting.id).where(
                    ApplyPosting.user_id == user.id, ApplyPosting.content_hash == posting.content_hash
                )
            )
        ).scalar_one_or_none() is not None:
            skipped += 1
            continue
        try:
            async with db.begin_nested():
                db.add(posting)
        except IntegrityError:
            skipped += 1
            continue
        new_ids.append(posting.id)

    source.last_status = f"Found {len(postings)} open roles, {len(matched)} matched your filters"[:300]
    if room <= 0:
        source.last_status = "Not imported: you have reached the maximum number of saved postings"
    source.last_new_count = len(new_ids)
    await db.flush()
    return {
        "found": len(postings), "matched_filters": len(matched), "new_postings": len(new_ids),
        "already_saved": skipped, "unreadable": unreadable, "new_posting_ids": new_ids,
    }


# -------------------------------------------------------------- packages --


async def get_package(db: AsyncSession, user_id: int, package_id: int) -> ApplyPackage:
    package = (
        await db.execute(
            select(ApplyPackage).where(ApplyPackage.id == package_id, ApplyPackage.user_id == user_id)
        )
    ).scalar_one_or_none()
    if package is None:
        raise _err(404, "not_found", "Application not found.")
    return package


def _event(db: AsyncSession, package: ApplyPackage, user_id: int, kind: str, *, detail: dict | str | None = None) -> None:
    text = json.dumps(detail) if isinstance(detail, dict) else detail
    db.add(ApplyPackageEvent(
        package_id=package.id, user_id=user_id, kind=kind, payload_hash=package.payload_hash,
        detail=(text or None) and text[:4000],
    ))


async def prepare_package(db: AsyncSession, user: User, posting: ApplyPosting, services: Services) -> ApplyPackage:
    if posting.status == "archived":
        raise _err(409, "archived", "Restore this posting before preparing an application.")
    facts = await candidate_facts(db, user)
    if not facts.has_resume:
        raise _err(409, "resume_required", "Add your resume (Profile & resume) before preparing an application.")
    if not posting.analysis_json:
        await _apply_analysis(db, user, posting, services=services, facts=facts)
    analysis = JDAnalysis.model_validate_json(posting.analysis_json)
    result = match(analysis, facts)  # always against the CURRENT resume and profile
    research = CompanyResearch.model_validate_json(posting.research_json) if posting.research_json else None
    # The employer's name and the role title are facts about the job, wherever
    # they came from (board metadata, the user's own label, or the posting).
    company_text = f"{posting.company}\n{posting.title}\n{_company_text(research)}"
    flagged = bool(_loads(posting.injection_json, []))

    tailored = tailor_resume(facts, analysis)
    report = guard.check(tailored.text, facts=facts, job_text=posting.raw_text)
    if not report.ok:
        # Tailoring only re-orders the user's own lines; a failure here is a bug.
        raise _err(500, "guard_failed", "The tailored resume failed its consistency check, so it was not used.")

    llm = None
    if (ai_configured() or services.llm_client is not None) and not flagged:
        llm = StructuredLLM(
            db, user_id=user.id, budget=RequestBudget(max_calls=settings.APPLY_AI_MAX_CALLS_PER_REQUEST),
            client=services.llm_client,
        )
    docs = await generate_documents(
        facts=facts, jd=analysis, match=result, job_text=posting.raw_text, company_text=company_text,
        llm=llm, allow_llm=llm is not None,
    )
    if flagged:
        docs.generation["cover_letter"] = {
            **docs.generation.get("cover_letter", {}),
            "ai_skipped": "This posting contains text that looks like instructions to an AI, so AI drafting was not used.",
        }
    for name, rep in docs.guard_reports.items():
        if not rep.ok:
            raise _err(500, "guard_failed", f"The {name.replace('_', ' ')} failed its consistency check, so it was not used.")

    base = await latest_resume(db, user.id)
    tailored_row = ApplyResume(
        user_id=user.id, kind="tailored", version=await _next_resume_version(db, user.id, "tailored"),
        text=tailored.text, posting_id=posting.id, base_resume_id=base.id if base else None,
        changes_json=json.dumps({
            "changes": tailored.changes, "emphasized": tailored.emphasized_keywords,
            "missing": tailored.missing_keywords,
        }),
    )
    try:
        async with db.begin_nested():
            db.add(tailored_row)
    except IntegrityError:
        raise _err(409, "concurrent_prepare", "Another draft for this posting is being prepared. Try again in a moment.") from None

    contact = docs.email_contact
    payload = {
        "what": (
            f"Application for {posting.title} at {posting.company}. Nothing is sent by Career Platform — "
            "after you approve, you submit it yourself."
        ),
        "who": {
            "employer": posting.company,
            "apply_url": posting.apply_url,
            "listing_url": posting.listing_url,
            "contact": (
                {"name": contact.name, "role": contact.role, "email": contact.email, "evidence": contact.evidence}
                if contact else None
            ),
        },
        "account": {
            "type": "manual",
            "description": "You send everything yourself, from your own accounts. Career Platform never sends email or submits forms.",
            "your_email": user.email,
        },
        "data": {
            "resume_text": tailored.text,
            "cover_letter": docs.cover_letter,
            "answers": [a.model_dump() for a in docs.answers],
            "email": (
                {"to": contact.email, "subject": docs.email.subject, "body": docs.email.body}
                if docs.email and contact else None
            ),
        },
        "attachments": [
            {"name": "Tailored resume", "kind": "resume", "characters": len(tailored.text)},
            {"name": "Cover letter", "kind": "cover_letter", "characters": len(docs.cover_letter)},
        ],
        "job": {"posting_id": posting.id, "title": posting.title, "company": posting.company},
    }
    body = canonical_json(payload)

    # Older open packages for this posting are superseded (kept for history).
    # Conditional UPDATE: a package approved or marked sent in the meantime is
    # never overwritten.
    superseded_ids = (
        await db.execute(
            update(ApplyPackage)
            .where(
                ApplyPackage.posting_id == posting.id,
                ApplyPackage.user_id == user.id,
                ApplyPackage.status.in_(["ready_for_review", "approved"]),
            )
            .values(status="superseded", updated_at=_now())
            .returning(ApplyPackage.id, ApplyPackage.payload_hash)
            .execution_options(synchronize_session=False)
        )
    ).all()
    for old_id, old_hash in superseded_ids:
        db.add(ApplyPackageEvent(package_id=old_id, user_id=user.id, kind="superseded", payload_hash=old_hash))

    version = (
        await db.execute(select(func.max(ApplyPackage.version)).where(ApplyPackage.posting_id == posting.id))
    ).scalar_one()
    package = ApplyPackage(
        user_id=user.id,
        posting_id=posting.id,
        version=int(version or 0) + 1,
        status="ready_for_review",
        resume_id=tailored_row.id,
        payload_json=body,
        payload_hash=sha256_hex(body),
        payload_version=1,
        guard_json=json.dumps({k: v.model_dump() for k, v in docs.guard_reports.items()}),
        generation_json=json.dumps({
            **docs.generation,
            "tailoring": {"changes": tailored.changes, "missing_keywords": tailored.missing_keywords},
            "match": {"score": result.score, "recommendation": result.recommendation, "gaps": result.gaps},
        }),
    )
    try:
        async with db.begin_nested():
            db.add(package)
    except IntegrityError:
        raise _err(409, "concurrent_prepare", "Another draft for this posting was just prepared. Open it from the posting.") from None
    _event(db, package, user.id, "created")
    await db.flush()
    return package


async def _cas(db: AsyncSession, package: ApplyPackage, expect: dict[str, Any], **values: Any) -> None:
    conditions = [ApplyPackage.id == package.id]
    for column, expected in expect.items():
        col = getattr(ApplyPackage, column)
        conditions.append(col.in_(expected) if isinstance(expected, (list, tuple)) else col == expected)
    result = await db.execute(
        update(ApplyPackage).where(*conditions).values(updated_at=_now(), **values)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise _err(409, "state_changed", "This application changed in the meantime. Reload it and review again.")
    await db.refresh(package)


def _apply_edits(payload: dict[str, Any], edits: dict[str, Any]) -> list[str]:
    unknown = set(edits) - _EDITABLE
    if unknown:
        raise _err(422, "not_editable", f"These fields can't be edited: {', '.join(sorted(unknown))}")
    data = payload["data"]
    changed: list[str] = []
    for key, value in edits.items():
        if key == "answers":
            if not isinstance(value, list):
                raise _err(422, "invalid_edit", "answers must be a list.")
            answers = data.get("answers") or []
            for item in value:
                idx = item.get("index") if isinstance(item, dict) else None
                text = item.get("answer") if isinstance(item, dict) else None
                if not isinstance(idx, int) or not 0 <= idx < len(answers) or not isinstance(text, str) or len(text) > 4000:
                    raise _err(422, "invalid_edit", "Invalid answer edit.")
                if answers[idx].get("answer") != text:
                    answers[idx]["answer"] = text
                    answers[idx]["edited_by_you"] = True
                    changed.append(f"answers[{idx}]")
            continue
        if not isinstance(value, str) or not value.strip():
            raise _err(422, "invalid_edit", f"{key.replace('_', ' ')} can't be empty.")
        if len(value) > _LIMITS[key]:
            raise _err(422, "invalid_edit", f"{key.replace('_', ' ')} is too long.")
        if key in {"email_subject", "email_body"}:
            email = data.get("email")
            if not email:
                raise _err(422, "invalid_edit", "This application has no email draft.")
            field_name = key.removeprefix("email_")
            if email.get(field_name) != value:
                email[field_name] = value
                changed.append(key)
            continue
        if data.get(key) != value:
            data[key] = value
            changed.append(key)
    return changed


async def edit_package(
    db: AsyncSession, user: User, package: ApplyPackage, *, base_hash: str, edits: dict[str, Any]
) -> tuple[ApplyPackage, bool, GuardReport | None]:
    """Apply edits. Returns (package, approval_voided, guard warnings for the edited text)."""
    if package.status not in ("ready_for_review", "approved"):
        raise _err(409, "invalid_state", f"This application can't be edited (it is {package.status.replace('_', ' ')}).")
    if base_hash != package.payload_hash:
        raise _err(409, "stale", "You edited an older version. Reload and try again.")
    payload = json.loads(package.payload_json)
    changed = _apply_edits(payload, edits)
    if not changed:
        return package, False, None
    body = canonical_json(payload)
    new_hash = sha256_hex(body)
    was_approved = package.status == "approved"
    await _cas(
        db, package, {"status": ["ready_for_review", "approved"], "payload_hash": base_hash},
        payload_json=body, payload_hash=new_hash, payload_version=package.payload_version + 1,
        status="ready_for_review", approved_payload_hash=None, approved_at=None, final_json=None,
    )
    _event(db, package, user.id, "edited", detail={"fields": changed, "previous_hash": base_hash,
                                                    "approval_voided": was_approved})
    # The user is the authority on their own facts; edits are not blocked, but
    # they are checked so the user can see anything the resume doesn't support.
    facts = await candidate_facts(db, user)
    posting = await get_posting(db, user.id, package.posting_id)
    edited_text = "\n".join(
        str(v) for k, v in edits.items() if k != "answers"
    ) + "\n" + "\n".join(str(a.get("answer", "")) for a in edits.get("answers", []) if isinstance(a, dict))
    report = None
    if edited_text.strip():
        report = await asyncio.to_thread(guard.check, edited_text, facts=facts, job_text=posting.raw_text)
    return package, was_approved, report


async def approve_package(db: AsyncSession, user: User, package: ApplyPackage, reviewed_hash: str) -> ApplyPackage:
    if package.status != "ready_for_review":
        raise _err(409, "invalid_state", f"Only applications waiting for review can be approved (this one is {package.status.replace('_', ' ')}).")
    if reviewed_hash != package.payload_hash:
        raise _err(409, "content_changed", "The content changed since you reviewed it. Review the latest version and approve again.")
    if sha256_hex(package.payload_json) != package.payload_hash:
        raise _err(409, "integrity", "Stored content failed its integrity check.")
    payload = json.loads(package.payload_json)
    final = {
        "approved_at": _now().isoformat(),
        "approved_payload_hash": reviewed_hash,
        "delivery": "manual",
        "instructions": (
            "Nothing was sent. Copy this final version, submit it on the employer's site (and send the "
            "email from your own account if there is one), then mark the application as sent."
        ),
        "who": payload.get("who"),
        "data": payload.get("data"),
    }
    await _cas(
        db, package, {"status": "ready_for_review", "payload_hash": reviewed_hash},
        status="approved", approved_payload_hash=reviewed_hash, approved_at=_now(),
        final_json=json.dumps(final, ensure_ascii=False),
    )
    _event(db, package, user.id, "approved")
    return package


async def reject_package(db: AsyncSession, user: User, package: ApplyPackage, reason: str | None) -> ApplyPackage:
    if package.status not in ("ready_for_review", "approved"):
        raise _err(409, "invalid_state", f"This application can't be rejected (it is {package.status.replace('_', ' ')}).")
    await _cas(db, package, {"status": ["ready_for_review", "approved"]}, status="rejected", final_json=None)
    _event(db, package, user.id, "rejected", detail=(reason or None) and reason[:1000])
    return package


async def mark_sent(db: AsyncSession, user: User, package: ApplyPackage, channel: str) -> tuple[ApplyPackage, Job]:
    if package.status != "approved":
        raise _err(409, "not_approved", "Approve the application before marking it as sent.")
    if package.approved_payload_hash != package.payload_hash or sha256_hex(package.payload_json) != package.payload_hash:
        raise _err(409, "content_changed", "The content no longer matches what you approved. Review it again.")
    await _cas(db, package, {"status": "approved", "payload_hash": package.approved_payload_hash},
               status="sent", sent_at=_now(), sent_channel=channel)
    _event(db, package, user.id, "marked_sent", detail={"channel": channel})
    posting = await get_posting(db, user.id, package.posting_id)
    job = await track_posting(db, user, posting, status_value="applied")
    if job.status != "applied" and job.status in ("saved",):
        job.status = "applied"
        job.applied_date = job.applied_date or date.today()
    await db.flush()
    return package, job


# ------------------------------------------------------------ serializers --


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def serialize_posting(posting: ApplyPosting, *, detail: bool = False) -> dict[str, Any]:
    match_data = _loads(posting.match_json, None)
    out: dict[str, Any] = {
        "id": posting.id,
        "title": posting.title,
        "company": posting.company,
        "location": posting.location,
        "location_type": posting.location_type,
        "source_type": posting.source_type,
        "listing_url": posting.listing_url,
        "apply_url": posting.apply_url,
        "fit_score": posting.fit_score,
        "recommendation": match_data.get("recommendation") if match_data else None,
        "status": posting.status,
        "tracked_job_id": posting.tracked_job_id,
        "flagged": bool(_loads(posting.injection_json, [])),
        "posted_at": _iso(posting.posted_at),
        "created_at": _iso(posting.created_at),
        "analyzed_at": _iso(posting.analyzed_at),
    }
    if detail:
        out.update({
            "analysis": _loads(posting.analysis_json, None),
            "match": match_data,
            "research": _loads(posting.research_json, None),
            "injection_findings": _loads(posting.injection_json, []),
            "text": posting.raw_text,
        })
    return out


def serialize_package(package: ApplyPackage, *, detail: bool = False, posting: ApplyPosting | None = None) -> dict[str, Any]:
    payload = _loads(package.payload_json, {})
    out: dict[str, Any] = {
        "id": package.id,
        "posting_id": package.posting_id,
        "version": package.version,
        "status": package.status,
        "title": (payload.get("job") or {}).get("title") or (posting.title if posting else None),
        "company": (payload.get("job") or {}).get("company") or (posting.company if posting else None),
        "payload_hash": package.payload_hash,
        "payload_version": package.payload_version,
        "has_email": bool((payload.get("data") or {}).get("email")),
        "approved_at": _iso(package.approved_at),
        "sent_at": _iso(package.sent_at),
        "sent_channel": package.sent_channel,
        "created_at": _iso(package.created_at),
        "updated_at": _iso(package.updated_at),
    }
    if detail:
        out.update({
            "payload": payload,
            "final": _loads(package.final_json, None),
            "guard": _loads(package.guard_json, {}),
            "generation": _loads(package.generation_json, {}),
        })
    return out


def serialize_source(source: ApplyDiscoverySource) -> dict[str, Any]:
    return {
        "id": source.id,
        "provider": source.provider,
        "board_token": source.board_token,
        "company_name": source.company_name,
        "keywords": _loads(source.keywords_json, []),
        "locations": _loads(source.locations_json, []),
        "last_run_at": _iso(source.last_run_at),
        "last_status": source.last_status,
        "last_new_count": source.last_new_count,
        "created_at": _iso(source.created_at),
    }

