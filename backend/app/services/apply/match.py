"""
Deterministic job ↔ candidate matching.

The score is a weighted average of components that can actually be computed
from the data at hand; a component with no data (e.g. the posting states no
years of experience) is left out and the remaining weights are renormalised,
instead of guessing. Each component carries a plain-language explanation so
the user sees why a job scored what it did.
"""

from __future__ import annotations

import re

from app.services.apply.candidate import CandidateFacts
from app.services.apply.schemas import JDAnalysis, MatchComponent, MatchResult

_WEIGHTS = {
    "required_skills": 0.55,
    "preferred_skills": 0.15,
    "experience": 0.15,
    "title": 0.10,
    "location": 0.05,
}
_STOP = {"and", "or", "the", "a", "an", "of", "for", "to", "in", "with", "at", "on", "ii", "iii", "i", "&", "-"}


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9+#.]+", text.lower()) if t not in _STOP and len(t) > 1}


def _title_score(jd_title: str | None, facts: CandidateFacts) -> tuple[float, str] | None:
    if not jd_title:
        return None
    targets = [t for t in [*facts.target_roles, facts.headline or ""] if t]
    if not targets:
        return None
    jd_tokens = _tokens(jd_title)
    if not jd_tokens:
        return None
    best = 0.0
    best_target = targets[0]
    for target in targets:
        t_tokens = _tokens(target)
        if not t_tokens:
            continue
        overlap = len(jd_tokens & t_tokens) / len(jd_tokens | t_tokens)
        if overlap > best:
            best, best_target = overlap, target
    score = min(1.0, best * 1.6)  # "Backend Engineer" vs "Senior Backend Engineer" → strong
    return score, f"Title '{jd_title}' vs your target '{best_target}'"


def _location_score(jd: JDAnalysis, facts: CandidateFacts) -> tuple[float, str] | None:
    if jd.location_type == "remote":
        if facts.open_to_remote:
            return 1.0, "Remote role and you're open to remote work"
        return 0.4, "Remote role, but your profile says you're not looking for remote"
    if not jd.location:
        return None
    wanted = [w.lower() for w in [*facts.target_locations, facts.location or ""] if w]
    if not wanted:
        return None
    jd_loc = jd.location.lower()
    for w in wanted:
        city = w.split(",")[0].strip()
        if city and city in jd_loc:
            return 1.0, f"Located in {jd.location}, which matches your preferences"
    kind = jd.location_type or "on-site"
    return 0.3, f"{kind.title()} in {jd.location}, outside your listed locations"


def match(jd: JDAnalysis, facts: CandidateFacts) -> MatchResult:
    have = {s.lower() for s in facts.skill_names}

    required = [s.name for s in jd.required_skills]
    preferred = [s.name for s in jd.preferred_skills]
    matched_req = [s for s in required if s.lower() in have]
    missing_req = [s for s in required if s.lower() not in have]
    matched_pref = [s for s in preferred if s.lower() in have]
    missing_pref = [s for s in preferred if s.lower() not in have]

    components: list[tuple[str, float, str]] = []
    if not facts.has_resume and not facts.skills:
        return MatchResult(
            score=0,
            confidence="low",
            recommendation="needs_profile",
            components=[],
            matched_required=[],
            missing_required=required,
            matched_preferred=[],
            missing_preferred=preferred,
            strengths=[],
            gaps=["Add your resume (or skills) so this job can be matched against your experience."],
        )

    if required:
        cov = len(matched_req) / len(required)
        components.append(
            ("required_skills", cov, f"You have {len(matched_req)} of {len(required)} skills the posting asks for")
        )
    if preferred:
        cov = len(matched_pref) / len(preferred)
        components.append(
            ("preferred_skills", cov, f"You have {len(matched_pref)} of {len(preferred)} nice-to-have skills")
        )
    if jd.min_years_experience is not None and facts.years_experience is not None:
        need, have_years = jd.min_years_experience, facts.years_experience
        score = 1.0 if have_years >= need else max(0.0, have_years / need)
        components.append(
            ("experience", score, f"Posting asks for {need}+ years; your profile says {have_years}")
        )
    title = _title_score(jd.title, facts)
    if title:
        components.append(("title", title[0], title[1]))
    loc = _location_score(jd, facts)
    if loc:
        components.append(("location", loc[0], loc[1]))

    total_weight = sum(_WEIGHTS[name] for name, _, _ in components) or 1.0
    raw = sum(_WEIGHTS[name] * score for name, score, _ in components) / total_weight
    score = round(raw * 100)

    has_skills_signal = bool(required) and len(required) >= 3
    confidence = (
        "high" if has_skills_signal and len(components) >= 3
        else "medium" if has_skills_signal or len(components) >= 3
        else "low"
    )
    recommendation = "strong" if score >= 75 else "possible" if score >= 50 else "stretch"

    strengths = [f"{s} — {facts.skills.get(s, '')}"[:200] for s in matched_req[:6]]
    gaps = []
    if missing_req:
        gaps.append("Not found in your resume or skills: " + ", ".join(missing_req[:10]))
    if jd.min_years_experience and facts.years_experience is not None and facts.years_experience < jd.min_years_experience:
        gaps.append(
            f"The posting asks for {jd.min_years_experience}+ years; your profile lists {facts.years_experience}."
        )
    if jd.min_years_experience and facts.years_experience is None:
        gaps.append("Add your years of experience to your profile to compare against this posting.")

    return MatchResult(
        score=max(0, min(100, score)),
        confidence=confidence,  # type: ignore[arg-type]
        recommendation=recommendation,  # type: ignore[arg-type]
        components=[
            MatchComponent(
                name=name,  # type: ignore[arg-type]
                score=round(score_, 3),
                weight=round(_WEIGHTS[name] / total_weight, 3),
                explanation=expl[:400],
            )
            for name, score_, expl in components
        ],
        matched_required=matched_req,
        missing_required=missing_req,
        matched_preferred=matched_pref,
        missing_preferred=missing_pref,
        strengths=strengths,
        gaps=gaps,
    )
