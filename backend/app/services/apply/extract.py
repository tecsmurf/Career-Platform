"""
Deterministic job-description analysis.

Turns a posting (plain text or HTML) into a ``JDAnalysis``: title, company,
location, seniority, experience, salary, required vs preferred skills,
responsibilities, qualifications, benefits, the company's own "about" text and
any contacts the employer published. Every extracted value comes from the
posting itself — most carry the line it was found on as evidence — so the
analysis can be shown to the user and audited.

No LLM is involved: the same posting always yields the same analysis.
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from app.services.apply.schemas import JDAnalysis, PostingContact, SalaryRange, SkillEvidence
from app.services.apply.skills import find_skills

EXTRACTION_VERSION = 1

_HTML_HINT = re.compile(r"<\s*(p|div|li|ul|ol|br|h[1-6]|span|strong|em|section|table)\b", re.I)
_BULLET = re.compile(r"^\s*(?:[-*•·▪◦●‣–—]|\d{1,2}[.)]|[a-z][.)])\s+")
_EMAIL = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63}){0,6}\.[A-Za-z]{2,24}(?![A-Za-z0-9-])"
)
_NAME = r"[A-Z][a-z'’-]+(?:\s+[A-Z][a-z'’-]+){1,2}"

_SECTION_KEYS: list[tuple[str, tuple[str, ...]]] = [
    (
        "preferred",
        (
            "nice to have", "nice-to-have", "preferred", "bonus", "pluses", "a plus",
            "desired", "good to have", "extra credit", "would be great",
        ),
    ),
    (
        "requirements",
        (
            "requirement", "qualification", "what you'll need", "what you will need",
            "what we're looking for", "what we are looking for", "must have", "must-have",
            "you have", "about you", "who you are", "what you bring", "skills", "experience",
            "you'll bring", "you will bring", "we're looking for", "we are looking for",
        ),
    ),
    (
        "responsibilities",
        (
            "responsibilit", "what you'll do", "what you will do", "the role", "your role",
            "duties", "day to day", "day-to-day", "in this role", "you will", "you'll",
            "what you'll be doing", "the job", "your impact", "key tasks",
        ),
    ),
    (
        "benefits",
        ("benefit", "perks", "what we offer", "compensation", "why join", "we offer", "why work"),
    ),
    ("about", ("about us", "about the company", "who we are", "our mission", "company overview", "about ")),
]

_TITLE_WORDS = re.compile(
    r"\b(engineer|developer|manager|designer|analyst|scientist|intern|lead|director|"
    r"specialist|consultant|architect|administrator|officer|coordinator|associate|"
    r"researcher|technician|representative|writer|editor|accountant|recruiter|"
    r"product|programmer|sre|devops|head of|vp|president|marketer|strategist)\b",
    re.I,
)


@dataclass
class _Sections:
    heading_order: list[str] = field(default_factory=list)
    lines: dict[str, list[str]] = field(default_factory=dict)


# ---------------------------------------------------------------- helpers --


def looks_like_html(text: str) -> bool:
    return bool(_HTML_HINT.search(text or ""))


def html_to_text(raw_html: str) -> tuple[str, list[str]]:
    """
    Convert HTML to readable text with one line per block / list item.

    Returns ``(text, hidden_snippets)``. Elements hidden with CSS or the
    ``hidden``/``aria-hidden`` attributes are REMOVED (they are invisible to a
    human reader, which is exactly how injected instructions are usually
    planted) and returned separately so they can be reported.
    """
    if "&lt;" in raw_html and "<" not in raw_html.replace("&lt;", ""):
        raw_html = html_lib.unescape(raw_html)  # Greenhouse sends escaped HTML
    soup = BeautifulSoup(raw_html, "lxml")
    for tag in soup(["script", "style", "noscript", "template", "svg", "iframe", "head", "meta", "link"]):
        tag.decompose()
    hidden: list[str] = []
    for tag in soup.find_all(True):
        if getattr(tag, "decomposed", False):
            continue
        style = (tag.get("style") or "").replace(" ", "").lower()
        if (
            tag.has_attr("hidden")
            or tag.get("aria-hidden") == "true"
            or "display:none" in style
            or "visibility:hidden" in style
            or "font-size:0" in style
            or "opacity:0" in style
        ):
            text = " ".join(tag.get_text(" ").split())
            if text:
                hidden.append(text[:300])
            tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for li in soup.find_all("li"):
        li.insert_before("\n• ")
        li.insert_after("\n")
    for tag in soup.find_all(["p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "ul", "ol"]):
        tag.insert_before("\n")
        tag.insert_after("\n")
    text = soup.get_text()
    return normalize_text(text), hidden


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    lines = [" ".join(line.split()) for line in text.split("\n")]
    out: list[str] = []
    for line in lines:
        if not line and (not out or not out[-1]):
            continue
        out.append(line)
    return "\n".join(out).strip()


def _strip_bullet(line: str) -> str:
    return _BULLET.sub("", line).strip()


def _heading_kind(line: str) -> str | None:
    raw = line.strip()
    candidate = raw.strip("#*_ ").rstrip(":").strip()
    if not candidate or len(candidate) > 70 or _BULLET.match(raw):
        return None
    if candidate.endswith(".") and len(candidate) > 25:
        return None
    lower = candidate.lower()
    words = len(candidate.split())
    is_heading_shape = (
        raw.endswith(":")
        or raw.startswith("#")
        or raw.startswith("**")
        or candidate.isupper()
        or words <= 6
    )
    if not is_heading_shape:
        return None
    for kind, keys in _SECTION_KEYS:
        if any(lower.startswith(k) or f" {k}" in f" {lower}" for k in keys):
            if kind == "about" and not (lower.startswith("about") or "who we are" in lower or "mission" in lower or "overview" in lower):
                continue
            return kind
    return None


def _split_sections(text: str) -> _Sections:
    sections = _Sections()
    current = "intro"
    sections.lines[current] = []
    sections.heading_order.append(current)
    for line in text.split("\n"):
        if not line.strip():
            continue
        kind = _heading_kind(line)
        if kind:
            current = kind
            if kind not in sections.lines:
                sections.lines[kind] = []
                sections.heading_order.append(kind)
            # "Requirements: 5+ years Python" — keep content after the colon.
            if ":" in line:
                rest = line.split(":", 1)[1].strip()
                if rest:
                    sections.lines[current].append(rest)
            continue
        sections.lines.setdefault(current, []).append(line.strip())
    return sections


def _clean_items(lines: list[str], limit: int = 40) -> list[str]:
    items: list[str] = []
    for line in lines:
        item = _strip_bullet(line)
        if _EMAIL.search(item):
            continue  # contact lines are reported as contacts, not list items
        if 3 <= len(item) <= 400 and item not in items:
            items.append(item)
        if len(items) >= limit:
            break
    return items


# ----------------------------------------------------------------- fields --


def _guess_title(lines: list[str], hint: str | None) -> str | None:
    if hint and hint.strip():
        return hint.strip()[:300]
    for line in lines[:6]:
        clean = _strip_bullet(line).strip("#* ")
        if 3 <= len(clean) <= 90 and _TITLE_WORDS.search(clean) and not clean.endswith("."):
            return clean
    return None


def _guess_company(text: str, sections: _Sections, hint: str | None) -> str | None:
    if hint and hint.strip():
        return hint.strip()[:300]
    for line in text.split("\n")[:80]:
        m = re.match(r"^\s*#*\**\s*About\s+((?:[A-Z0-9][\w&.'’-]*\s?){1,5})\s*:?\**\s*$", line)
        if m and m.group(1).strip().lower() not in {"us", "the company", "the role", "you", "the team"}:
            return m.group(1).strip()[:300]
    about = " ".join(sections.lines.get("about", [])[:2])
    m = re.match(r"^((?:[A-Z][\w&.'’-]*\s?){1,4})\s+(?:is|are|builds|helps|was founded)\b", about)
    if m:
        return m.group(1).strip()[:300]
    return None


def _location(text: str) -> tuple[str | None, str | None]:
    lower = text.lower()
    remote = bool(re.search(r"\b(fully\s+)?remote\b", lower)) and not re.search(
        r"\b(not|no)\s+(a\s+)?remote\b|\bnon-remote\b", lower
    )
    hybrid = bool(re.search(r"\bhybrid\b", lower))
    onsite = bool(re.search(r"\b(on-?site|in[- ]office|in[- ]person)\b", lower))
    location_type = "hybrid" if hybrid else "remote" if remote else "onsite" if onsite else None

    location = None
    m = re.search(r"(?im)^\s*(?:location|based in|office|where)\s*[:\-]\s*(.{2,120})$", text)
    if m:
        location = m.group(1).strip().rstrip(".")
    else:
        m = re.search(
            r"\b([A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)?,\s(?:[A-Z]{2}|[A-Z][a-z]+(?:\s[A-Z][a-z]+)?))\b",
            "\n".join(text.split("\n")[:8]),
        )
        if m:
            location = m.group(1)
    return location, location_type


def _employment_type(text: str) -> str | None:
    lower = text.lower()
    for pattern, value in (
        (r"\b(internship|intern)\b", "internship"),
        (r"\bpart[- ]time\b", "part_time"),
        (r"\b(contract|contractor|fixed[- ]term)\b", "contract"),
        (r"\bfreelance\b", "freelance"),
        (r"\btemporary\b", "temporary"),
        (r"\bfull[- ]time\b", "full_time"),
    ):
        if re.search(pattern, lower):
            return value
    return None


def _seniority(title: str | None, min_years: int | None) -> str | None:
    t = (title or "").lower()
    rules = (
        (r"\b(intern|internship|graduate|junior|jr\.?|entry[- ]level|apprentice)\b", "entry"),
        (r"\b(chief|vp|vice president|director|head of)\b", "executive"),
        (r"\b(principal|staff|distinguished)\b", "principal"),
        (r"\b(lead|manager)\b", "lead"),
        (r"\b(senior|sr\.?)\b", "senior"),
        (r"\b(mid[- ]level|intermediate)\b", "mid"),
    )
    for pattern, value in rules:
        if re.search(pattern, t):
            return value
    if min_years is not None:
        if min_years >= 8:
            return "principal"
        if min_years >= 5:
            return "senior"
        if min_years >= 2:
            return "mid"
        return "entry"
    return None


_YEARS = re.compile(
    r"(?:at\s+least|minimum(?:\s+of)?|min\.?)?\s*(\d{1,2})\s*\+?\s*(?:(?:-|–|to)\s*\d{1,2}\s*\+?\s*)?"
    r"(?:years?|yrs?)\b",
    re.I,
)


def _min_years(sections: _Sections) -> tuple[int | None, str | None]:
    order = ["requirements", "intro", "responsibilities", "preferred"]
    for key in order:
        for line in sections.lines.get(key, []):
            if not re.search(r"experience|professional|industry|working", line, re.I):
                continue
            for m in _YEARS.finditer(line):
                years = int(m.group(1))
                if 0 < years <= 30:
                    return years, line[:300]
    return None, None


_MONEY = r"(\d{1,3}(?:[,.]\d{3})+|\d+(?:\.\d+)?)\s*([kK])?"
_SALARY = re.compile(
    r"(?P<cur>[$£€₹]|USD|EUR|GBP|INR|CAD|AUD)\s?" + _MONEY
    + r"\s*(?:-|–|—|to)\s*(?:[$£€₹]|USD|EUR|GBP|INR|CAD|AUD)?\s?" + _MONEY,
)
_CURRENCY = {"$": "USD", "£": "GBP", "€": "EUR", "₹": "INR"}


def _to_amount(number: str, k: str | None) -> int | None:
    digits = number.replace(",", "")
    if digits.count(".") > 1 or (digits.count(".") == 1 and len(digits.split(".")[1]) == 3):
        digits = digits.replace(".", "")
    try:
        value = float(digits)
    except ValueError:
        return None
    if k:
        value *= 1000
    return int(value)


def _salary(text: str) -> SalaryRange | None:
    for line in text.split("\n"):
        m = _SALARY.search(line)
        if not m:
            continue
        low = _to_amount(m.group(2), m.group(3))
        high = _to_amount(m.group(4), m.group(5) or m.group(3))
        if low is None or high is None or high < low or high > 10_000_000:
            continue
        lower = line.lower()
        period = (
            "hour" if re.search(r"per\s+hour|/\s*h(ou)?r|hourly", lower)
            else "month" if re.search(r"per\s+month|/\s*mo(nth)?|monthly", lower)
            else "year"
        )
        if period == "year" and high < 1000:
            continue
        cur = m.group("cur")
        return SalaryRange(
            min=low, max=high, currency=_CURRENCY.get(cur, cur), period=period, evidence=line[:300]
        )
    return None


def _education(text: str) -> str | None:
    m = re.search(
        r"(?im)^.*\b(bachelor'?s?|master'?s?|ph\.?d|b\.?s\.?c?|m\.?s\.?c?|b\.?tech|m\.?tech|mba|"
        r"degree in|undergraduate degree)\b.*$",
        text,
    )
    return _strip_bullet(m.group(0))[:300] if m else None


def extract_contacts(text: str) -> list[PostingContact]:
    """People/addresses the employer published in the posting. Nothing is guessed."""
    contacts: list[PostingContact] = []
    seen_emails: set[str] = set()
    lines = text.split("\n")
    for line in lines:
        for m in _EMAIL.finditer(line):
            email = m.group(0).strip(".").lower()
            local = email.split("@", 1)[0]
            if len(email) > 254 or email in seen_emails or re.search(r"no-?reply|do-?not-?reply|privacy|legal|unsubscribe", local):
                continue
            seen_emails.add(email)
            name = None
            role = None
            nm = re.search(rf"\b(?:[Cc]ontact|[Rr]each out to|[Ee]-?mail|[Ww]rite to)\s*:?\s*({_NAME})", line)
            if nm:
                name = nm.group(1)
            else:
                nm = re.search(rf"({_NAME})\s*,?\s*\(?\s*(?:our\s+|the\s+)?(?:senior\s+)?(?:technical\s+)?(recruiter|talent|hiring manager|recruiting)", line, re.I)
                if nm:
                    name = nm.group(1)
            rm = re.search(r"\b((?:senior\s+|technical\s+)?recruiter|talent (?:partner|acquisition)|hiring manager|recruiting(?: team)?|people team|hr team)\b", line, re.I)
            if rm:
                role = rm.group(1).strip().title()
            elif re.match(r"(jobs|careers|recruiting|talent|hr|hiring)$", local):
                role = "Recruiting team"
            contacts.append(PostingContact(name=name, role=role, email=email, evidence=line.strip()[:500]))
            if len(contacts) >= 10:
                return contacts
    for line in lines:
        m = re.search(rf"\b(recruiter|hiring manager|talent partner|point of contact)\s*[:\-]\s*({_NAME})", line, re.I)
        if m and not any(c.name == m.group(2) for c in contacts):
            contacts.append(
                PostingContact(name=m.group(2), role=m.group(1).title(), email=None, evidence=line.strip()[:500])
            )
    return contacts[:10]


# ------------------------------------------------------------------- main --


def analyze_posting(
    raw: str,
    *,
    title_hint: str | None = None,
    company_hint: str | None = None,
) -> tuple[JDAnalysis, str, list[str]]:
    """
    Analyze a posting. Returns ``(analysis, normalized_text, hidden_snippets)``.

    ``normalized_text`` is the plain text the analysis was computed from —
    store it as the job's description so evidence lines can be found in it.
    ``hidden_snippets`` is text that was hidden from human readers in the
    HTML (removed from the analysis; reported as suspicious).
    """
    hidden: list[str] = []
    if looks_like_html(raw):
        text, hidden = html_to_text(raw)
    else:
        text = normalize_text(raw)
    sections = _split_sections(text)
    lines = [ln for ln in text.split("\n") if ln.strip()]

    title = _guess_title(lines, title_hint)
    company = _guess_company(text, sections, company_hint)
    location, location_type = _location(text)
    min_years, years_evidence = _min_years(sections)

    preferred_text = "\n".join(sections.lines.get("preferred", []))
    other_text = "\n".join(
        line for key, ls in sections.lines.items() if key not in {"preferred", "benefits", "about"} for line in ls
    )
    if title:
        other_text = f"{title}\n{other_text}"
    required_hits = find_skills(other_text)
    required_names = {h.name for h in required_hits}
    preferred_hits = [h for h in find_skills(preferred_text) if h.name not in required_names]

    responsibilities = _clean_items(sections.lines.get("responsibilities", []))
    qualifications = _clean_items(
        sections.lines.get("requirements", []) + sections.lines.get("preferred", [])
    )
    benefits = _clean_items(sections.lines.get("benefits", []), limit=25)
    about = " ".join(sections.lines.get("about", []))[:2000] or None

    keywords: list[str] = []
    for name in [h.name for h in required_hits] + [h.name for h in preferred_hits]:
        if name not in keywords:
            keywords.append(name)

    analysis = JDAnalysis(
        extraction_version=EXTRACTION_VERSION,
        title=title,
        company=company,
        location=location[:300] if location else None,
        location_type=location_type,  # type: ignore[arg-type]
        employment_type=_employment_type(text),  # type: ignore[arg-type]
        seniority=_seniority(title, min_years),  # type: ignore[arg-type]
        min_years_experience=min_years,
        years_evidence=years_evidence,
        salary=_salary(text),
        required_skills=[SkillEvidence(name=h.name, category=h.category, evidence=h.evidence) for h in required_hits][:80],
        preferred_skills=[SkillEvidence(name=h.name, category=h.category, evidence=h.evidence) for h in preferred_hits][:80],
        responsibilities=responsibilities,
        qualifications=qualifications,
        benefits=benefits,
        education=_education(text),
        about_company=about,
        contacts=extract_contacts(text),
        keywords=keywords[:60],
        word_count=len(text.split()),
    )
    return analysis, text, hidden
