"""
Public job-board clients (Greenhouse, Lever, Ashby).

These boards publish documented, unauthenticated JSON APIs so that anyone can
list a company's open roles. FK Apply only reads them; it never logs in,
never submits applications through them and never bypasses any control.

Requests go through ``SafeFetcher`` with an exact host allow-list, and the
board token is validated against a strict pattern before it is placed in the
URL path, so user input cannot redirect the request.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from app.services.apply.fetcher import JSON_TYPES, FetchError, SafeFetcher


class DiscoveryProvider(str, Enum):
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"

BOARD_TOKEN_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")

PROVIDER_HOSTS: dict[DiscoveryProvider, str] = {
    DiscoveryProvider.GREENHOUSE: "boards-api.greenhouse.io",
    DiscoveryProvider.LEVER: "api.lever.co",
    DiscoveryProvider.ASHBY: "api.ashbyhq.com",
}


class DiscoveryError(Exception):
    """User-safe description of a discovery failure."""


@dataclass
class DiscoveredPosting:
    source_job_id: str
    title: str
    location: str | None
    listing_url: str | None
    apply_url: str | None
    description: str  # HTML or text
    posted_at: datetime | None
    remote: bool | None = None


def board_url(provider: DiscoveryProvider, token: str) -> str:
    if not BOARD_TOKEN_RE.match(token):
        raise DiscoveryError("Board name may only contain lowercase letters, digits, '.', '_' and '-'")
    host = PROVIDER_HOSTS[provider]
    if provider is DiscoveryProvider.GREENHOUSE:
        return f"https://{host}/v1/boards/{token}/jobs?content=true"
    if provider is DiscoveryProvider.LEVER:
        return f"https://{host}/v0/postings/{token}?mode=json"
    return f"https://{host}/posting-api/job-board/{token}?includeCompensation=true"


def _str(value: Any, limit: int = 500) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()[:limit]
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(value)
    return None


def _https(value: Any) -> str | None:
    url = _str(value, 2000)
    return url if url and url.startswith("https://") else None


def _dt_iso(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(value, int | float) and value > 10**11:  # Lever: epoch milliseconds
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    return None


def parse_greenhouse(data: Any) -> list[DiscoveredPosting]:
    jobs = data.get("jobs") if isinstance(data, dict) else None
    out: list[DiscoveredPosting] = []
    for job in jobs if isinstance(jobs, list) else []:
        if not isinstance(job, dict):
            continue
        jid, title = _str(job.get("id"), 100), _str(job.get("title"), 300)
        if not jid or not title:
            continue
        loc = job.get("location")
        out.append(
            DiscoveredPosting(
                source_job_id=jid,
                title=title,
                location=_str(loc.get("name"), 300) if isinstance(loc, dict) else None,
                listing_url=_https(job.get("absolute_url")),
                apply_url=_https(job.get("absolute_url")),
                description=_str(job.get("content"), 200_000) or "",
                posted_at=_dt_iso(job.get("updated_at") or job.get("first_published")),
            )
        )
    return out


def parse_lever(data: Any) -> list[DiscoveredPosting]:
    out: list[DiscoveredPosting] = []
    for job in data if isinstance(data, list) else []:
        if not isinstance(job, dict):
            continue
        jid, title = _str(job.get("id"), 100), _str(job.get("text"), 300)
        if not jid or not title:
            continue
        cats = job.get("categories") if isinstance(job.get("categories"), dict) else {}
        parts = [_str(job.get("description"), 100_000) or _str(job.get("descriptionPlain"), 100_000) or ""]
        for block in job.get("lists") or []:
            if isinstance(block, dict):
                heading = _str(block.get("text"), 200) or ""
                content = _str(block.get("content"), 50_000) or ""
                parts.append(f"<h3>{heading}</h3><ul>{content}</ul>")
        extra = _str(job.get("additional"), 50_000)
        if extra:
            parts.append(extra)
        out.append(
            DiscoveredPosting(
                source_job_id=jid,
                title=title,
                location=_str(cats.get("location"), 300),
                listing_url=_https(job.get("hostedUrl")),
                apply_url=_https(job.get("applyUrl")) or _https(job.get("hostedUrl")),
                description="\n".join(parts),
                posted_at=_dt_iso(job.get("createdAt")),
                remote=(job.get("workplaceType") == "remote") if job.get("workplaceType") else None,
            )
        )
    return out


def parse_ashby(data: Any) -> list[DiscoveredPosting]:
    jobs = data.get("jobs") if isinstance(data, dict) else None
    out: list[DiscoveredPosting] = []
    for job in jobs if isinstance(jobs, list) else []:
        if not isinstance(job, dict) or job.get("isListed") is False:
            continue
        jid, title = _str(job.get("id"), 100), _str(job.get("title"), 300)
        if not jid or not title:
            continue
        out.append(
            DiscoveredPosting(
                source_job_id=jid,
                title=title,
                location=_str(job.get("location"), 300),
                listing_url=_https(job.get("jobUrl")),
                apply_url=_https(job.get("applyUrl")) or _https(job.get("jobUrl")),
                description=_str(job.get("descriptionHtml"), 200_000) or _str(job.get("descriptionPlain"), 200_000) or "",
                posted_at=_dt_iso(job.get("publishedAt")),
                remote=job.get("isRemote") if isinstance(job.get("isRemote"), bool) else None,
            )
        )
    return out


_PARSERS = {
    DiscoveryProvider.GREENHOUSE: parse_greenhouse,
    DiscoveryProvider.LEVER: parse_lever,
    DiscoveryProvider.ASHBY: parse_ashby,
}


def matches_filters(posting: DiscoveredPosting, keywords: list[str], locations: list[str]) -> bool:
    title = posting.title.lower()
    if keywords and not any(k.lower() in title for k in keywords if k.strip()):
        return False
    if locations:
        where = (posting.location or "").lower()
        wanted = [loc.lower() for loc in locations if loc.strip()]
        remote_ok = "remote" in wanted and (posting.remote or "remote" in where)
        if not remote_ok and not any(loc in where for loc in wanted):
            return False
    return True


async def fetch_board(
    provider: DiscoveryProvider, token: str, fetcher: SafeFetcher
) -> list[DiscoveredPosting]:
    url = board_url(provider, token)
    try:
        page = await fetcher.get(url, allowed_hosts={PROVIDER_HOSTS[provider]}, accept_types=JSON_TYPES)
    except FetchError as exc:
        raise DiscoveryError(f"Could not read the {provider.value} board '{token}': {exc}") from exc
    try:
        data = json.loads(page.text)
    except ValueError as exc:
        raise DiscoveryError("The job board returned invalid data") from exc
    return _PARSERS[provider](data)
