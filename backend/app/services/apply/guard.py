"""
Fabrication guard.

Checks a generated document (cover letter, answers, email, tailored resume)
against the sources it is allowed to draw on:

* the candidate's own facts (profile, skills list, the exact resume snapshot);
* the job posting text and verified company facts — for statements ABOUT the
  job or the company, never as evidence about the candidate.

A claim about the candidate (a sentence in the first person) may only mention
skills, credentials, numbers, names, links and contact details that appear in
the candidate's facts. Anything else is a violation and the document is not
used. The guard is deliberately strict — a false positive costs an AI draft
(FK Apply falls back to the deterministic draft built only from verified
facts); a false negative could put an invented claim in front of an employer.
"""

from __future__ import annotations

import re
from functools import lru_cache

from app.services.apply.candidate import CandidateFacts
from app.services.apply.schemas import GuardReport, GuardViolation
from app.services.apply.skills import find_skills, mentions

_PLACEHOLDER = re.compile(
    r"(\[\s*(?:insert|your|company|name|role|title|position|date|x+)[^\]]{0,40}\]|"
    r"\[\s*[A-Z][A-Za-z]{1,20}(?:\s+[A-Z][A-Za-z]{1,20}){0,3}\s*\]|"
    r"\{\{?\s*[a-z_ ]{1,30}\s*\}?\}|<\s*[A-Z_]{3,30}\s*>|lorem ipsum|\bXXX+\b|\bTBD\b|\[\s*\.\.\.\s*\])",
    re.I,
)
_FIRST_PERSON = re.compile(r"\b(I|I'm|I’m|I've|I’ve|I'd|I’d|my|me|mine|myself)\b")
_LEARNING = re.compile(
    r"\b(learn|learning|eager to|keen to|excited to (?:grow|develop|build skills)|"
    r"not yet|working toward|would welcome the chance to (?:learn|grow))\b",
    re.I,
)
_NUMBER = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)(?![\w])")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_URL = re.compile(r"\b(?:https?://|www\.)[^\s)>\]]+", re.I)
_CREDENTIAL = re.compile(
    r"\b(bachelor'?s?|master'?s?|ph\.?\s?d\.?|doctorate|mba|b\.?\s?tech|m\.?\s?tech|b\.?sc?|m\.?sc?|"
    r"certified|certification|certificate|licensed|license|cpa|pmp|cfa)\b",
    re.I,
)
_NUMBER_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
    "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12", "fifteen": "15",
    "twenty": "20",
}
_YEARS_WORDS = re.compile(
    r"\b(" + "|".join(_NUMBER_WORDS) + r")\s*\+?\s+years?\b", re.I
)
# Capitalised words that are not names of things.
_COMMON_CAPS = {
    "i", "i'm", "i’m", "i've", "i’ve", "i'd", "i’d", "dear", "hello", "hi", "sincerely", "regards",
    "best", "kind", "warm", "thank", "thanks", "hiring", "team", "manager", "recruiter", "the",
    "a", "an", "and", "or", "in", "on", "at", "for", "with", "my", "your", "our", "this", "that",
    "these", "those", "as", "it", "to", "of", "from", "by", "re", "subject", "mr", "ms", "mrs",
    "dr", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december", "linkedin", "github", "portfolio", "website", "email",
    "phone", "resume", "cv", "cover", "letter", "application", "role", "position", "company",
    "talent", "acquisition", "people", "recruiting", "hr", "ai", "please", "looking", "would",
    "could", "should", "while", "when", "during", "after", "before", "since", "most",
    "recently", "currently", "previously", "also", "additionally", "finally", "first", "second",
    "summary", "experience", "education", "skills", "projects", "certifications", "why",
    "what", "how", "which", "who", "where", "yes", "no", "not", "available", "upon", "request",
    "remote", "hybrid", "onsite", "on-site", "full-time", "part-time", "contract", "senior",
    "junior", "lead", "principal", "staff", "engineer", "engineering", "developer", "designer",
    "analyst", "scientist", "product", "data", "software", "backend", "frontend", "full",
    "stack", "web", "mobile", "cloud", "platform", "infrastructure", "security", "machine",
    "learning", "here", "there", "over", "across", "through", "including", "both", "each",
    "every", "many", "several", "highlights", "relevant", "answer", "question", "note",
    "needs", "input", "you", "you're", "you’re", "we", "we're", "they", "he", "she", "his",
    "her", "their", "its", "if", "so", "but", "because", "although", "though", "again", "all",
    "any", "some", "more", "much", "very", "really", "just", "only", "then", "than", "now",
    "today", "tomorrow", "next", "last", "new", "applying", "applied", "interested", "excited",
    "grateful", "happy", "glad", "eager", "keen", "confident", "sure", "please,", "let",
    "looking", "following", "attached", "enclosed", "below", "above",
}


_TOKEN = re.compile(r"[a-z0-9&.'’+#-]+")


def _token_set(text_lower: str) -> set[str]:
    """Every word of the sources, plus forms without trailing punctuation / possessive."""
    tokens: set[str] = set()
    for tok in _TOKEN.findall(text_lower):
        tokens.add(tok)
        stripped = tok.strip(".'’-")
        tokens.add(stripped)
        tokens.add(re.sub(r"['’]s$", "", stripped))
    return tokens


@lru_cache(maxsize=4096)
def _is_skill_word(word: str) -> bool:
    return bool(find_skills(word))


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def _digits(value: str) -> str:
    return value.replace(",", "").rstrip(".")


def _number_set(text: str) -> set[str]:
    out = {_digits(m.group(1)) for m in _NUMBER.finditer(text)}
    for word, digit in _NUMBER_WORDS.items():
        if re.search(rf"\b{word}\b", text, re.I):
            out.add(digit)
    return out


def check(
    generated: str,
    *,
    facts: CandidateFacts,
    job_text: str = "",
    company_text: str = "",
    extra_allowed: str = "",
) -> GuardReport:
    """Validate ``generated`` against the allowed sources. See module docstring."""
    violations: list[GuardViolation] = []
    warnings: list[str] = []

    candidate_src = f"{facts.source_text()}\n{extra_allowed}"
    context_src = f"{job_text}\n{company_text}"
    all_src = f"{candidate_src}\n{context_src}"
    all_src_lower = all_src.lower()
    all_tokens = _token_set(all_src_lower)
    candidate_lower = candidate_src.lower()
    have_skills = {s.lower() for s in facts.skill_names}

    def add(kind: str, text: str, detail: str) -> None:
        if len(violations) < 25:
            violations.append(GuardViolation(kind=kind, text=text[:300], detail=detail[:300]))

    if not generated.strip():
        return GuardReport(ok=False, violations=[GuardViolation(kind="empty", text="", detail="Document is empty")])

    for m in _PLACEHOLDER.finditer(generated):
        add("placeholder", m.group(0), "Unfilled placeholder text")

    candidate_numbers = _number_set(candidate_src)
    all_numbers = _number_set(all_src)

    for sentence in _sentences(generated):
        first_person = bool(_FIRST_PERSON.search(sentence))

        # Skills: a first-person sentence may only claim skills the user has.
        for hit in find_skills(sentence):
            if hit.name.lower() in have_skills:
                continue
            if first_person:
                if not _LEARNING.search(sentence):
                    add("unsupported_skill", sentence, f"'{hit.name}' is not in your resume or skills list")
            elif not mentions(context_src, hit.name):
                # Not a claim about the user, but not from the posting either.
                add("unsupported_skill", sentence, f"'{hit.name}' appears in neither your facts nor the posting")

        # Numbers: claims about the user need the number in the user's facts;
        # statements about the job may use numbers from the posting.
        allowed_numbers = candidate_numbers if first_person else all_numbers
        for m in _NUMBER.finditer(sentence):
            number = _digits(m.group(1))
            if number not in allowed_numbers:
                add("unsupported_number", sentence, f"The number {m.group(1)} is not in your facts")
        for m in _YEARS_WORDS.finditer(sentence):
            digit = _NUMBER_WORDS[m.group(1).lower()]
            if first_person and digit not in candidate_numbers:
                add("unsupported_number", sentence, f"'{m.group(0)}' is not in your facts")

        # Credentials (degrees, certifications) claimed by the user.
        if first_person:
            for m in _CREDENTIAL.finditer(sentence):
                term = m.group(1).lower().replace(" ", "")
                if term not in candidate_lower.replace(" ", ""):
                    add("unsupported_credential", sentence, f"'{m.group(1)}' is not in your facts")

        # Proper names (employers, schools, products) in claims about the user.
        if first_person:
            words = re.findall(r"(?<![\w@./-])([A-Z][A-Za-z0-9&.'’-]{1,40})", sentence)
            for idx, word in enumerate(words):
                bare = re.sub(r"['’]s$", "", word).strip(".'’")
                low = bare.lower()
                if low in _COMMON_CAPS or len(bare) < 2:
                    continue
                if sentence.startswith(word) and idx == 0:
                    continue  # sentence-initial capital
                if low in all_tokens:
                    continue
                if _is_skill_word(bare):
                    continue  # skill names are checked above
                add("unverified_name", sentence, f"'{bare}' does not appear in your facts or the posting")

    # Contact details and links must come from the sources verbatim.
    for m in _EMAIL.finditer(generated):
        if m.group(0).lower() not in all_src_lower:
            add("unverified_contact", m.group(0), "Email address not found in your facts or the posting")
    for m in _URL.finditer(generated):
        url = m.group(0).rstrip(".,;").lower()
        bare = re.sub(r"^https?://", "", url).rstrip("/")
        if bare not in all_src_lower:
            add("unverified_link", m.group(0), "Link not found in your facts or the posting")

    if len(generated) > 50 and generated.count("\n") == 0 and len(generated) > 1500:
        warnings.append("Very long single paragraph")

    return GuardReport(ok=not violations, violations=violations, warnings=warnings)
