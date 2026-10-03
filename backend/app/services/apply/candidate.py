"""
Candidate facts — the canonical, user-provided source of truth.

Everything FK Apply writes about the user (tailored resume, cover letter,
answers, emails) must be supported by these facts. They come only from what
the user entered: their profile, their skills list and the exact resume
snapshot being tailored. The fabrication guard checks generated text against
``CandidateFacts.source_text``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from app.services.apply.skills import canonicalize, find_skills

_RESUME_HEADINGS = {
    "summary": ("summary", "profile", "about me", "objective", "professional summary"),
    "experience": (
        "experience", "work experience", "professional experience", "employment",
        "work history", "career history",
    ),
    "projects": ("projects", "selected projects", "personal projects"),
    "education": ("education", "academic background"),
    "skills": ("skills", "technical skills", "core skills", "technologies", "tools"),
    "certifications": ("certifications", "certificates", "licenses"),
    "other": ("awards", "publications", "volunteering", "interests", "languages", "achievements"),
}


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        data = json.loads(value)
    except (TypeError, ValueError):
        return [v.strip() for v in value.split(",") if v.strip()]
    return [str(v).strip() for v in data if str(v).strip()] if isinstance(data, list) else []


def resume_heading(line: str) -> str | None:
    """Return the section kind if ``line`` is a resume section heading."""
    clean = line.strip().strip("#*_:").strip().lower()
    if not clean or len(clean) > 40:
        return None
    for kind, names in _RESUME_HEADINGS.items():
        if clean in names:
            return kind
    return None


@dataclass
class ResumeSection:
    kind: str
    heading: str | None
    lines: list[str] = field(default_factory=list)


def split_resume(text: str) -> list[ResumeSection]:
    sections: list[ResumeSection] = [ResumeSection(kind="header", heading=None)]
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        kind = resume_heading(line)
        if kind:
            sections.append(ResumeSection(kind=kind, heading=line.strip()))
            continue
        sections[-1].lines.append(line)
    return sections


@dataclass
class CandidateFacts:
    user_id: str
    full_name: str
    email: str
    phone: str | None = None
    links: dict[str, str] = field(default_factory=dict)
    location: str | None = None
    headline: str | None = None
    summary: str | None = None
    years_experience: int | None = None
    target_roles: list[str] = field(default_factory=list)
    target_locations: list[str] = field(default_factory=list)
    open_to_remote: bool = True
    resume_text: str = ""
    resume_version_id: str | None = None
    skills: dict[str, str] = field(default_factory=dict)  # canonical/explicit name → evidence

    @property
    def has_resume(self) -> bool:
        return len(self.resume_text.strip()) >= 50

    @property
    def skill_names(self) -> set[str]:
        return set(self.skills)

    def resume_bullets(self) -> list[str]:
        """Achievement-style lines from experience/projects sections."""
        out: list[str] = []
        for section in split_resume(self.resume_text):
            if section.kind not in {"experience", "projects", "header"}:
                continue
            for line in section.lines:
                stripped = re.sub(r"^\s*(?:[-*•·▪◦●‣–]|\d{1,2}[.)])\s+", "", line).strip()
                if len(stripped.split()) >= 6 and stripped != line.strip() or len(stripped.split()) >= 9:
                    out.append(stripped)
        return out

    def source_text(self) -> str:
        """Every user-provided fact as one text blob (the guard's ground truth)."""
        parts = [
            self.full_name,
            self.email,
            self.phone or "",
            self.location or "",
            self.headline or "",
            self.summary or "",
            f"{self.years_experience} years" if self.years_experience is not None else "",
            " ".join(self.links.values()),
            " ".join(self.target_roles),
            " ".join(self.target_locations),
            self.resume_text,
            "\n".join(f"{k} {v}" for k, v in self.skills.items()),
        ]
        return "\n".join(p for p in parts if p)


def build_candidate_facts(
    *,
    user_id: int,
    full_name: str,
    email: str,
    profile: object | None,
    resume_text: str | None,
    resume_version_id: int | None,
) -> CandidateFacts:
    """Assemble facts from the user, their apply profile and one resume version."""
    facts = CandidateFacts(
        user_id=str(user_id),
        full_name=full_name or "",
        email=email or "",
        resume_text=(resume_text or "").strip(),
        resume_version_id=str(resume_version_id) if resume_version_id is not None else None,
    )
    explicit_skills: list[str] = []
    if profile is not None:
        links: dict[str, str] = {}
        for key, label in (
            ("linkedin_url", "linkedin"),
            ("github_url", "github"),
            ("portfolio_url", "portfolio"),
            ("website_url", "website"),
        ):
            value = getattr(profile, key, None)
            if value:
                links[label] = value
        facts.links = links
        facts.location = getattr(profile, "location", None) or None
        facts.phone = getattr(profile, "phone", None)
        facts.headline = getattr(profile, "headline", None)
        facts.summary = getattr(profile, "summary", None)
        facts.years_experience = getattr(profile, "years_experience", None)
        facts.target_roles = _json_list(getattr(profile, "target_roles_json", None))
        facts.target_locations = _json_list(getattr(profile, "target_locations_json", None))
        facts.open_to_remote = bool(getattr(profile, "open_to_remote", True))
        explicit_skills = _json_list(getattr(profile, "skills_json", None))

    skills: dict[str, str] = {}
    for hit in find_skills(facts.resume_text):
        skills[hit.name] = f"resume: {hit.evidence}"
    for hit in find_skills(facts.summary or ""):
        skills.setdefault(hit.name, f"profile summary: {hit.evidence}")
    for raw in explicit_skills:
        name = canonicalize(raw) or raw.strip()
        if name:
            skills.setdefault(name, "added to your skills list")
    facts.skills = skills
    return facts
