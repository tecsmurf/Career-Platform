"""
Daily job feed — adds a few fresh openings to every user's Postings list each day.

Once a day (see ``app/jobs/daily_feed.py`` and the GitHub Actions workflow),
every curated public job board is read once, then each user gets up to
``DAILY_FEED_PER_USER`` (default 5) new postings:

* picked to fit their profile when they have one (target roles, target
  locations, remote preference), falling back to the newest openings;
* spread across different companies, newest first;
* never a posting they already have (same board id or same text), so the
  feed never repeats itself;
* idempotent per UTC day: running the job twice adds nothing the second time.

The postings are ordinary board postings (``source_type`` = the board, no
``discovery_source_id``), analysed and matched exactly like a manual board
import, so the API and the frontend need no changes to show them.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import User
from app.models.apply import ApplyPosting
from app.models.auth import UserAuthState
from app.services.apply.discovery import (
    DiscoveredPosting, DiscoveryError, DiscoveryProvider, fetch_board, matches_filters,
)
from app.services.apply.service import (
    Services, _apply_analysis, _loads, active_posting_count, candidate_facts, content_hash, get_profile,
)

log = logging.getLogger("app.daily_feed")

# Public boards with documented, unauthenticated JSON APIs. A board that has
# moved or closed just fails that day and is skipped. Override with the
# DAILY_FEED_BOARDS setting ("provider:token:Company Name,..."), no deploy needed.
DEFAULT_BOARDS: tuple[tuple[str, str, str], ...] = (
    ("greenhouse", "figma", "Figma"),
    ("greenhouse", "discord", "Discord"),
    ("greenhouse", "gitlab", "GitLab"),
    ("greenhouse", "cloudflare", "Cloudflare"),
    ("greenhouse", "airbnb", "Airbnb"),
    ("greenhouse", "dropbox", "Dropbox"),
    ("greenhouse", "duolingo", "Duolingo"),
    ("greenhouse", "reddit", "Reddit"),
    ("greenhouse", "robinhood", "Robinhood"),
    ("greenhouse", "databricks", "Databricks"),
    ("greenhouse", "pinterest", "Pinterest"),
    ("lever", "plaid", "Plaid"),
    ("lever", "palantir", "Palantir"),
    ("ashby", "notion", "Notion"),
    ("ashby", "ramp", "Ramp"),
    ("ashby", "linear", "Linear"),
    ("ashby", "openai", "OpenAI"),
)

BOARD_PROVIDERS = tuple(p.value for p in DiscoveryProvider)


@dataclass(frozen=True)
class Board:
    provider: DiscoveryProvider
    token: str
    company: str


@dataclass
class Candidate:
    board: Board
    posting: DiscoveredPosting


def configured_boards() -> list[Board]:
    raw = settings.DAILY_FEED_BOARDS.strip()
    entries: list[tuple[str, str, str]] = []
    if raw:
        for item in raw.split(","):
            parts = [p.strip() for p in item.split(":", 2)]
            if len(parts) == 3 and all(parts):
                entries.append((parts[0].lower(), parts[1].lower(), parts[2]))
            elif item.strip():
                log.warning("Ignoring malformed DAILY_FEED_BOARDS entry %r", item.strip())
    boards: list[Board] = []
    for provider, token, company in entries or DEFAULT_BOARDS:
        try:
            boards.append(Board(DiscoveryProvider(provider), token, company[:200]))
        except ValueError:
            log.warning("Ignoring unknown provider %r in daily feed boards", provider)
    return boards


async def collect_candidates(services: Services, boards: list[Board]) -> tuple[list[Candidate], dict[str, str]]:
    """Read every board once. Returns (candidates, {board: error}) — failures never stop the run."""
    candidates: list[Candidate] = []
    errors: dict[str, str] = {}
    fetcher = services.get_fetcher()
    for board in boards:
        try:
            found = await fetch_board(board.provider, board.token, fetcher)
        except DiscoveryError as exc:
            errors[f"{board.provider.value}:{board.token}"] = str(exc)
            continue
        candidates.extend(Candidate(board, p) for p in found)
    return candidates, errors


def _utc_day_start(now: datetime) -> datetime:
    return now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _posted(c: Candidate) -> float:
    if c.posting.posted_at is None:
        return 0.0
    dt = c.posting.posted_at
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()


def rank_for_user(
    candidates: list[Candidate], *, roles: list[str], locations: list[str], open_to_remote: bool, seed: str,
) -> list[Candidate]:
    """Best-fitting openings first, one company at a time, newest first within a company."""
    wanted_locations = [loc for loc in locations if loc.strip()]
    if wanted_locations and open_to_remote and "remote" not in [w.lower() for w in wanted_locations]:
        wanted_locations.append("remote")
    tiers = [
        [c for c in candidates if matches_filters(c.posting, roles, wanted_locations)],
        [c for c in candidates if matches_filters(c.posting, roles, [])] if roles else [],
        list(candidates),
    ]
    ordered: list[Candidate] = []
    seen: set[tuple[str, str]] = set()
    rng = random.Random(seed)
    for tier in tiers:
        by_company: dict[str, list[Candidate]] = {}
        for c in sorted(tier, key=_posted, reverse=True):
            key = (c.board.provider.value, c.posting.source_job_id)
            if key in seen:
                continue
            seen.add(key)
            by_company.setdefault(c.board.company, []).append(c)
        companies = list(by_company)
        rng.shuffle(companies)  # a different company mix each day, stable within a day
        while companies:
            for company in list(companies):
                ordered.append(by_company[company].pop(0))
                if not by_company[company]:
                    companies.remove(company)
    return ordered


async def feed_postings_today(db: AsyncSession, user_id: int, now: datetime) -> int:
    return int((
        await db.execute(
            select(func.count(ApplyPosting.id)).where(
                ApplyPosting.user_id == user_id,
                ApplyPosting.source_type.in_(BOARD_PROVIDERS),
                ApplyPosting.discovery_source_id.is_(None),
                ApplyPosting.created_at >= _utc_day_start(now),
            )
        )
    ).scalar_one())


async def add_daily_postings(
    db: AsyncSession, user: User, candidates: list[Candidate], services: Services, *, now: datetime | None = None,
) -> list[int]:
    """Add up to DAILY_FEED_PER_USER new postings for one user. Returns the new posting ids."""
    now = now or datetime.now(timezone.utc)
    want = settings.DAILY_FEED_PER_USER - await feed_postings_today(db, user.id, now)
    room = settings.APPLY_MAX_POSTINGS_PER_USER - await active_posting_count(db, user.id)
    want = min(want, room)
    if want <= 0 or not candidates:
        return []

    profile = await get_profile(db, user.id)
    roles = _loads(profile.target_roles_json, []) if profile else []
    locations = _loads(profile.target_locations_json, []) if profile else []
    ranked = rank_for_user(
        candidates, roles=roles, locations=locations,
        open_to_remote=profile.open_to_remote if profile else True,
        seed=f"{user.id}:{_utc_day_start(now).date().isoformat()}",
    )
    facts = await candidate_facts(db, user)
    new_ids: list[int] = []
    for cand in ranked:
        if len(new_ids) >= want:
            break
        item, board = cand.posting, cand.board
        exists = (
            await db.execute(
                select(ApplyPosting.id).where(
                    ApplyPosting.user_id == user.id,
                    ApplyPosting.source_type == board.provider.value,
                    ApplyPosting.source_job_id == item.source_job_id,
                )
            )
        ).scalar_one_or_none()
        if exists is not None:
            continue
        posting = ApplyPosting(
            user_id=user.id,
            source_type=board.provider.value,
            source_job_id=item.source_job_id,
            listing_url=item.listing_url,
            apply_url=item.apply_url,
            title=item.title[:300],
            company=board.company[:300],
            location=item.location,
            raw_text=(item.description or item.title)[:200_000],
            posted_at=item.posted_at,
            status="analyzed",
        )
        try:
            # No per-posting outbound requests and no AI: analysed from the posting itself.
            await _apply_analysis(db, user, posting, services=services, facts=facts, site_lookup=False)
        except ValidationError:
            continue
        posting.content_hash = content_hash(posting.raw_text)
        if (
            await db.execute(
                select(ApplyPosting.id).where(
                    ApplyPosting.user_id == user.id, ApplyPosting.content_hash == posting.content_hash
                )
            )
        ).scalar_one_or_none() is not None:
            continue
        try:
            async with db.begin_nested():
                db.add(posting)
        except IntegrityError:
            continue
        new_ids.append(posting.id)
    await db.flush()
    return new_ids


async def eligible_user_ids(db: AsyncSession) -> list[int]:
    """Active users who finished sign-up (an unverified sign-up gets nothing)."""
    pending = select(UserAuthState.user_id).where(UserAuthState.signup_pending.is_(True))
    rows = await db.execute(
        select(User.id).where(User.is_active.is_(True), User.id.not_in(pending)).order_by(User.id)
    )
    return [int(r) for r in rows.scalars().all()]


async def run_daily_feed(session_factory, services: Services | None = None) -> dict:
    """Run the whole feed: read the boards once, then fill each user in their own transaction."""
    services = services or Services()
    summary = {"users": 0, "users_updated": 0, "postings_added": 0, "candidates": 0, "board_errors": {}}
    if not settings.DAILY_FEED_ENABLED or settings.DAILY_FEED_PER_USER <= 0:
        summary["skipped"] = "daily feed is disabled"
        return summary
    candidates, errors = await collect_candidates(services, configured_boards())
    summary["candidates"], summary["board_errors"] = len(candidates), errors
    for key, err in errors.items():
        log.warning("Daily feed: board %s skipped: %s", key, err)
    if not candidates:
        return summary

    async with session_factory() as db:
        user_ids = await eligible_user_ids(db)
    summary["users"] = len(user_ids)
    for user_id in user_ids:
        async with session_factory() as db:
            try:
                user = await db.get(User, user_id)
                if user is None:
                    continue
                added = await add_daily_postings(db, user, candidates, services)
                await db.commit()
            except Exception:  # one user's failure must not stop everyone else's feed
                await db.rollback()
                log.exception("Daily feed failed for user %s", user_id)
                continue
        if added:
            summary["users_updated"] += 1
            summary["postings_added"] += len(added)
    return summary
