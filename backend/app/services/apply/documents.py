"""
Application documents: cover letter, application answers, outreach email.

Each document has a deterministic version assembled only from verified facts:
the user's own resume lines, profile fields and skills, plus job/company facts
taken from the posting. Anything personal or legal that FK Apply cannot know
(work authorization, salary expectations, notice period, relocation) is NOT
answered — it is returned with ``needs_user_input=True``.

The cover letter can optionally be redrafted by the LLM. The AI draft is used
only if it passes the fabrication guard; otherwise the deterministic letter
is kept and the reason is recorded for the user.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.apply import guard
from app.services.apply.candidate import CandidateFacts
from app.services.apply.llm import LLMUnavailable, StructuredLLM
from app.services.apply.schemas import (
    ApplicationAnswer,
    EmailDraft,
    GuardReport,
    JDAnalysis,
    LLMCoverLetter,
    MatchResult,
    PostingContact,
)
from app.services.apply.skills import find_skills


@dataclass
class GeneratedDocs:
    cover_letter: str
    answers: list[ApplicationAnswer]
    email: EmailDraft | None
    email_contact: PostingContact | None
    generation: dict[str, dict[str, object]] = field(default_factory=dict)
    guard_reports: dict[str, GuardReport] = field(default_factory=dict)


def _top_bullets(facts: CandidateFacts, jd: JDAnalysis, limit: int = 3) -> list[str]:
    wanted = {s.name for s in jd.required_skills} | {s.name for s in jd.preferred_skills}
    scored: list[tuple[float, int, str]] = []
    for idx, bullet in enumerate(facts.resume_bullets()):
        hits = {h.name for h in find_skills(bullet)}
        score = 2.0 * len(hits & wanted) + (0.5 if re.search(r"\d", bullet) else 0.0)
        if score > 0:
            scored.append((score, -idx, bullet))
    scored.sort(reverse=True)
    # Verbatim resume lines (only trailing punctuation trimmed) — the user's own words.
    return [bullet.rstrip(".;") for _, _, bullet in scored[:limit]]


def _signature(facts: CandidateFacts) -> str:
    lines = [facts.full_name]
    if facts.email:
        lines.append(facts.email)
    if facts.phone:
        lines.append(facts.phone)
    for key in ("linkedin", "github", "portfolio", "website"):
        if facts.links.get(key):
            lines.append(facts.links[key])
    return "\n".join(lines)


def _addressee(contact: PostingContact | None, company: str) -> str:
    if contact and contact.name:
        return f"Dear {contact.name},"
    return f"Dear {company} hiring team,"


def deterministic_cover_letter(
    facts: CandidateFacts,
    jd: JDAnalysis,
    match: MatchResult,
    contact: PostingContact | None,
) -> str:
    company = jd.company or "your company"
    title = jd.title or "the open role"
    paras: list[str] = [_addressee(contact, company)]

    opening = f"I'm applying for the {title} position at {company}."
    if facts.headline:
        opening += f" I'm a {facts.headline.strip().rstrip('.')}"
        if facts.years_experience:
            opening += f" with {facts.years_experience} years of experience"
        opening += "."
    paras.append(opening)

    matched = match.matched_required[:5]
    bullets = _top_bullets(facts, jd)
    if matched or bullets:
        body = ""
        if matched:
            body += (
                "The role calls for "
                + ", ".join(matched[:-1])
                + (" and " if len(matched) > 1 else "")
                + matched[-1]
                + ", which are core parts of my work."
            )
        if bullets:
            body += " Some relevant highlights from my experience:"
        paras.append(body.strip())
        if bullets:
            paras.append("\n".join(f"- {b}" for b in bullets))

    if jd.about_company:
        paras.append(
            f"What draws me to {company} is the work described in your posting, and I would "
            "welcome the chance to contribute to it."
        )
    paras.append(
        "Thank you for considering my application. I would be glad to discuss how my experience "
        "fits what your team needs."
    )
    paras.append("Sincerely,\n" + _signature(facts))
    return "\n\n".join(paras)


_PERSONAL_QUESTIONS = (
    ("Are you legally authorized to work in this location? Will you need sponsorship?",
     "Work authorization is personal and legal information FK Apply cannot know — please answer it yourself."),
    ("What are your salary expectations?",
     "Salary expectations are your decision — FK Apply does not guess them."),
    ("When can you start / what is your notice period?",
     "Your availability is personal — please answer it yourself."),
)


def deterministic_answers(facts: CandidateFacts, jd: JDAnalysis, match: MatchResult) -> list[ApplicationAnswer]:
    company = jd.company or "the company"
    title = jd.title or "this role"
    answers: list[ApplicationAnswer] = []

    why = f"The {title} role lines up with what I do best"
    if match.matched_required:
        why += f": it centres on {', '.join(match.matched_required[:4])}, which I work with"
    why += "."
    if jd.about_company:
        why += f" I'm also interested in the work at {company} described in the posting."
    answers.append(
        ApplicationAnswer(
            question=f"Why are you interested in this role at {company}?",
            answer=why,
            basis="Skills you share with the posting; the posting's description of the company",
        )
    )

    bullets = _top_bullets(facts, jd, limit=3)
    if bullets:
        rel = "Relevant experience from my resume:\n" + "\n".join(f"- {b}" for b in bullets)
        basis = "Verbatim lines from your resume most related to this posting"
        needs = False
    else:
        rel = "Add a short example of relevant work here."
        basis = "No resume lines matched this posting's skills"
        needs = True
    answers.append(
        ApplicationAnswer(
            question="Describe your most relevant experience for this role.",
            answer=rel,
            basis=basis,
            needs_user_input=needs,
        )
    )

    if facts.years_experience is not None:
        answers.append(
            ApplicationAnswer(
                question="How many years of relevant experience do you have?",
                answer=f"{facts.years_experience} years.",
                basis="Years of experience from your profile",
            )
        )
    for question, note in _PERSONAL_QUESTIONS:
        answers.append(ApplicationAnswer(question=question, answer="", basis=note, needs_user_input=True))
    return answers


def deterministic_email(
    facts: CandidateFacts,
    jd: JDAnalysis,
    match: MatchResult,
    contact: PostingContact,
) -> EmailDraft:
    company = jd.company or "your team"
    title = jd.title or "the open role"
    greeting = f"Hi {contact.name.split()[0]}," if contact.name else "Hello,"
    lines = [greeting, ""]
    lines.append(f"I've applied for the {title} position at {company} and wanted to introduce myself.")
    if facts.headline:
        intro = f"I'm a {facts.headline.strip().rstrip('.')}"
        if match.matched_required:
            intro += f" working with {', '.join(match.matched_required[:3])}"
        lines.append(intro + ".")
    bullets = _top_bullets(facts, jd, limit=1)
    if bullets:
        lines.append(f"One highlight from my resume: {bullets[0]}.")
    lines.append("")
    lines.append("I'd be glad to share more about my background if it would help. Thank you for your time.")
    lines.append("")
    lines.append("Best regards,")
    lines.append(_signature(facts))
    return EmailDraft(subject=f"{title} application — {facts.full_name}"[:200], body="\n".join(lines))


def _email_contact(jd: JDAnalysis) -> PostingContact | None:
    for c in jd.contacts:
        if c.email:
            return c
    return None


async def generate_documents(
    *,
    facts: CandidateFacts,
    jd: JDAnalysis,
    match: MatchResult,
    job_text: str,
    company_text: str,
    llm: StructuredLLM | None,
    allow_llm: bool,
) -> GeneratedDocs:
    contact = _email_contact(jd)
    named_contact = contact or next((c for c in jd.contacts if c.name), None)

    letter = deterministic_cover_letter(facts, jd, match, named_contact)
    generation: dict[str, dict[str, object]] = {"cover_letter": {"mode": "deterministic"}}
    reports: dict[str, GuardReport] = {}

    if llm is not None and allow_llm:
        try:
            draft = await llm.generate(
                feature="cover_letter",
                schema=LLMCoverLetter,
                instructions=(
                    "Write a concise, specific cover letter (220-380 words) for the candidate, for the job "
                    "in job_facts. Use only candidate_facts for anything about the candidate; mention only "
                    "skills listed in candidate_facts.skills. Address it using `addressee`. End with "
                    "'Sincerely,' followed by `signature` exactly. Return {\"cover_letter\": \"...\"}."
                ),
                data={
                    "candidate_facts": {
                        "name": facts.full_name,
                        "headline": facts.headline,
                        "years_experience": facts.years_experience,
                        "skills": sorted(facts.skill_names),
                        "resume_highlights": facts.resume_bullets()[:12],
                    },
                    "job_facts": {
                        "title": jd.title,
                        "company": jd.company,
                        "required_skills": [s.name for s in jd.required_skills],
                        "responsibilities": jd.responsibilities[:10],
                        "about_company": jd.about_company,
                    },
                    "matched_skills": match.matched_required,
                    "addressee": _addressee(named_contact, jd.company or "your company"),
                    "signature": _signature(facts),
                },
            )
            report = guard.check(draft.cover_letter, facts=facts, job_text=job_text, company_text=company_text)
            if report.ok:
                letter = draft.cover_letter
                generation["cover_letter"] = {"mode": "llm", "model_checked": True}
            else:
                generation["cover_letter"] = {
                    "mode": "deterministic",
                    "ai_draft_discarded": True,
                    "reason": "The AI draft made claims not supported by your resume: "
                    + "; ".join(v.detail for v in report.violations[:3]),
                }
                await llm.record(feature="cover_letter_guard", model=None, status="rejected_ai_draft")
        except LLMUnavailable as exc:
            generation["cover_letter"] = {"mode": "deterministic", "ai_unavailable": exc.reason}

    answers = deterministic_answers(facts, jd, match)
    email = deterministic_email(facts, jd, match, contact) if contact else None
    generation["answers"] = {"mode": "deterministic"}
    if email:
        generation["email"] = {"mode": "deterministic"}

    reports["cover_letter"] = guard.check(letter, facts=facts, job_text=job_text, company_text=company_text)
    reports["answers"] = guard.check(
        "\n".join(a.answer for a in answers if a.answer), facts=facts, job_text=job_text, company_text=company_text
    )
    if email:
        reports["email"] = guard.check(
            f"{email.subject}\n{email.body}", facts=facts, job_text=job_text, company_text=company_text,
            extra_allowed=f"{contact.name or ''} {contact.email or ''}" if contact else "",
        )
    return GeneratedDocs(
        cover_letter=letter,
        answers=answers,
        email=email,
        email_contact=contact,
        generation=generation,
        guard_reports=reports,
    )
