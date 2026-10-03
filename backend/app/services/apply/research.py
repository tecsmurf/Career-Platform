"""
Company research — verified facts first, interpretation clearly labelled.

``verified_facts`` only contains statements copied from a source FK Apply
actually read (the posting, or the company's own homepage), each with the
source and the exact excerpt. ``interpretation`` is derived automatically and
is always presented as interpretation, never as fact.

Website research is limited to the company's own homepage title and meta
description, fetched through the SSRF-safe fetcher. No people search, no
scraping of social networks, no guessing.
"""

from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from app.services.apply.fetcher import HTML_TYPES, FetchError, SafeFetcher
from app.services.apply.injection import scan
from app.services.apply.schemas import CompanyResearch, JDAnalysis, ResearchFact

# Job boards / ATS hosts: their domain is not the employer's domain.
_ATS_HOSTS = (
    "greenhouse.io", "lever.co", "ashbyhq.com", "myworkdayjobs.com", "workday.com",
    "smartrecruiters.com", "icims.com", "jobvite.com", "bamboohr.com", "workable.com",
    "linkedin.com", "indeed.com", "glassdoor.com", "wellfound.com", "angel.co",
    "ziprecruiter.com", "monster.com", "recruitee.com", "teamtailor.com", "breezy.hr",
    "jazzhr.com", "applytojob.com", "personio.de", "rippling.com", "dover.com",
)
_CATEGORY_LABEL = {
    "language": "programming languages",
    "frontend": "frontend development",
    "backend": "backend services",
    "data": "data infrastructure and analytics",
    "ml": "machine learning",
    "cloud_devops": "cloud and DevOps",
    "security": "security",
    "testing": "testing and quality",
    "mobile": "mobile development",
    "engineering": "systems engineering",
    "design": "design",
    "product_business": "product and business",
    "soft": "collaboration and leadership",
}


def _host(url: str | None) -> str | None:
    if not url:
        return None
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return None
    return host or None


def _is_ats(host: str) -> bool:
    return any(host == h or host.endswith("." + h) for h in _ATS_HOSTS)


def company_domain(listing_url: str | None, apply_url: str | None, job_text: str) -> str | None:
    """The employer's own domain, if one can be identified without guessing."""
    for url in (listing_url, apply_url):
        host = _host(url)
        if host and not _is_ats(host):
            return host.removeprefix("www.")
    for m in re.finditer(r"https://[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?:/[^\s)]*)?", job_text):
        host = _host(m.group(0))
        if host and not _is_ats(host):
            return host.removeprefix("www.")
    return None


def _line_with(text: str, needle: str) -> str:
    for line in text.split("\n"):
        if needle.lower() in line.lower():
            return line.strip()[:500]
    return needle[:500]


def _posting_facts(jd: JDAnalysis, job_text: str, source_url: str | None) -> list[ResearchFact]:
    facts: list[ResearchFact] = []

    def add(label: str, value: str, excerpt: str) -> None:
        facts.append(
            ResearchFact(
                label=label, value=value[:1000], source="job posting", source_url=source_url, excerpt=excerpt[:500]
            )
        )

    if jd.company:
        add("Company", jd.company, _line_with(job_text, jd.company))
    if jd.about_company:
        add("About (in the company's words)", jd.about_company, jd.about_company)
    if jd.location:
        add("Location", jd.location, _line_with(job_text, jd.location))
    if jd.location_type:
        add("Work arrangement", jd.location_type, _line_with(job_text, jd.location_type))
    if jd.salary:
        cur = jd.salary.currency or ""
        add(
            "Stated pay range",
            f"{cur} {jd.salary.min:,}–{jd.salary.max:,} per {jd.salary.period}".strip(),
            jd.salary.evidence,
        )
    pay_line = jd.salary.evidence.lstrip("-*•· ").strip() if jd.salary else None
    benefits = [b for b in jd.benefits if b != pay_line]
    if benefits:
        add("Stated benefits", "; ".join(benefits[:6]), "; ".join(benefits[:6]))
    return facts


def _interpretation(jd: JDAnalysis) -> tuple[list[str], str]:
    cats = Counter(s.category for s in jd.required_skills)
    themes = [f"Heavy emphasis on {_CATEGORY_LABEL.get(c, c)}" for c, _ in cats.most_common(3)]
    if jd.seniority in {"senior", "lead", "principal"}:
        themes.append("Expects a high level of ownership (senior-level role)")
    if any(re.search(r"\bmentor|lead\b", r, re.I) for r in jd.responsibilities):
        themes.append("Mentoring or leading others is part of the job")
    return themes[:6], "Derived automatically from the skills and responsibilities in the posting — not verified"


async def _website_facts(domain: str, fetcher: SafeFetcher) -> tuple[list[ResearchFact], list[str]]:
    url = f"https://{domain}/"
    try:
        page = await fetcher.get(url, accept_types=HTML_TYPES)
    except FetchError as exc:
        return [], [f"Company website not read: {exc}"]
    soup = BeautifulSoup(page.text[:500_000], "lxml")
    found: list[tuple[str, str]] = []
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    if title:
        found.append(("Website title", title))
    for attrs in ({"name": "description"}, {"property": "og:description"}):
        tag = soup.find("meta", attrs=attrs)
        content = tag.get("content") if tag else None
        if isinstance(content, str) and content.strip():
            found.append(("Website description", content.strip()))
            break
    facts: list[ResearchFact] = []
    notes: list[str] = []
    for label, value in found:
        if scan(value):
            notes.append(f"{label} skipped: it contained text that looks like instructions to an AI")
            continue
        value = " ".join(value.split())[:500]
        facts.append(
            ResearchFact(label=label, value=value, source="company website", source_url=page.final_url, excerpt=value)
        )
    return facts, notes


async def research_company(
    *,
    jd: JDAnalysis,
    job_text: str,
    listing_url: str | None,
    apply_url: str | None,
    fetcher: SafeFetcher | None,
    allow_fetch: bool,
) -> CompanyResearch:
    domain = company_domain(listing_url, apply_url, job_text)
    facts = _posting_facts(jd, job_text, listing_url)
    notes: list[str] = []
    if allow_fetch and fetcher is not None and domain:
        site_facts, site_notes = await _website_facts(domain, fetcher)
        facts.extend(site_facts)
        notes.extend(site_notes)
    elif not domain:
        notes.append("No company website could be identified from the posting (job-board links are not used)")
    themes, basis = _interpretation(jd)
    return CompanyResearch(
        company=(jd.company or "Unknown company")[:300],
        domain=domain,
        verified_facts=facts[:30],
        interpretation=themes,
        interpretation_basis=basis,
        notes=notes[:10],
    )
