"""
Typed contracts for everything the pipeline produces.

Every JSON blob FK Apply stores (job analysis, match, research, documents,
LLM output) is built through — or validated against — one of these models.
``extra="forbid"`` everywhere: an LLM (or a bug) adding unexpected fields is a
validation failure, not silently persisted data.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---------------------------------------------------------------- analysis --


class SkillEvidence(_Strict):
    name: str = Field(max_length=100)
    category: str = Field(max_length=50)
    evidence: str = Field(max_length=300)


class SalaryRange(_Strict):
    min: int | None = Field(default=None, ge=0, le=10_000_000)
    max: int | None = Field(default=None, ge=0, le=10_000_000)
    currency: str | None = Field(default=None, max_length=10)
    period: Literal["year", "month", "hour"] | None = None
    evidence: str = Field(max_length=300)


class PostingContact(_Strict):
    name: str | None = Field(default=None, max_length=200)
    role: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    evidence: str = Field(max_length=500)


class JDAnalysis(_Strict):
    extraction_version: int = 1
    title: str | None = Field(default=None, max_length=300)
    company: str | None = Field(default=None, max_length=300)
    location: str | None = Field(default=None, max_length=300)
    location_type: Literal["remote", "hybrid", "onsite"] | None = None
    employment_type: (
        Literal["full_time", "part_time", "contract", "internship", "freelance", "temporary"] | None
    ) = None
    seniority: Literal["entry", "mid", "senior", "lead", "principal", "executive"] | None = None
    min_years_experience: int | None = Field(default=None, ge=0, le=50)
    years_evidence: str | None = Field(default=None, max_length=300)
    salary: SalaryRange | None = None
    required_skills: list[SkillEvidence] = Field(default_factory=list, max_length=80)
    preferred_skills: list[SkillEvidence] = Field(default_factory=list, max_length=80)
    responsibilities: list[str] = Field(default_factory=list, max_length=40)
    qualifications: list[str] = Field(default_factory=list, max_length=40)
    benefits: list[str] = Field(default_factory=list, max_length=40)
    education: str | None = Field(default=None, max_length=300)
    about_company: str | None = Field(default=None, max_length=2000)
    contacts: list[PostingContact] = Field(default_factory=list, max_length=10)
    keywords: list[str] = Field(default_factory=list, max_length=60)
    word_count: int = 0


# ------------------------------------------------------------------- match --


class MatchComponent(_Strict):
    name: Literal["required_skills", "preferred_skills", "experience", "title", "location"]
    score: float = Field(ge=0, le=1)
    weight: float = Field(ge=0, le=1)
    explanation: str = Field(max_length=400)


class MatchResult(_Strict):
    score: int = Field(ge=0, le=100)
    confidence: Literal["high", "medium", "low"]
    recommendation: Literal["strong", "possible", "stretch", "needs_profile"]
    components: list[MatchComponent]
    matched_required: list[str]
    missing_required: list[str]
    matched_preferred: list[str]
    missing_preferred: list[str]
    strengths: list[str]
    gaps: list[str]


# ---------------------------------------------------------------- research --


class ResearchFact(_Strict):
    label: str = Field(max_length=100)
    value: str = Field(max_length=1000)
    source_url: str | None = Field(default=None, max_length=2000)
    source: str = Field(max_length=100)  # "job posting" | "company website" | ...
    excerpt: str = Field(max_length=500)


class CompanyResearch(_Strict):
    company: str = Field(max_length=300)
    domain: str | None = Field(default=None, max_length=300)
    verified_facts: list[ResearchFact] = Field(default_factory=list, max_length=30)
    interpretation: list[str] = Field(default_factory=list, max_length=10)
    interpretation_basis: str = Field(default="", max_length=300)
    notes: list[str] = Field(default_factory=list, max_length=10)


# --------------------------------------------------------------- documents --


class TailoredResume(_Strict):
    text: str = Field(max_length=40_000)
    changes: list[str] = Field(max_length=50)
    emphasized_keywords: list[str] = Field(max_length=60)
    missing_keywords: list[str] = Field(max_length=60)


class ApplicationAnswer(_Strict):
    question: str = Field(max_length=300)
    answer: str = Field(max_length=4000)
    basis: str = Field(max_length=300)
    needs_user_input: bool = False


class EmailDraft(_Strict):
    subject: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=20, max_length=6000)


class GuardViolation(_Strict):
    kind: str = Field(max_length=50)
    text: str = Field(max_length=300)
    detail: str = Field(max_length=300)


class GuardReport(_Strict):
    ok: bool
    violations: list[GuardViolation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# -------------------------------------------------------- LLM output shapes --


class LLMCoverLetter(_Strict):
    """What the cover-letter model may return. Nothing else is accepted."""

    cover_letter: str = Field(min_length=200, max_length=6000)


class LLMRoleSummary(_Strict):
    """AI interpretation of a posting — always shown labelled as interpretation."""

    summary: str = Field(min_length=20, max_length=800)
    themes: list[str] = Field(default_factory=list, max_length=6)
