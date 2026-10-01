"""
Rule-based job-email detection & extraction (always available, deterministic).
=============================================================================

Pipeline:  headers → pre-filter → (body fetched) → category scoring →
           structured extraction → confidence

Principles:
- Never fabricate: an extracted value must literally appear in the email
  (sender, subject or body); otherwise the field is left empty (None).
- Categories are scored, not first-match, so "Thank you for applying ...
  unfortunately we will not be moving forward" is a rejection.
- Email text is data. Nothing in it is ever executed or treated as an instruction.
"""
import re
from dataclasses import dataclass, replace
from datetime import date

from app.services.email.parsing import ParsedEmail, ParsedHeaders

CATEGORIES = (
    "application_confirmation", "interview_invitation", "rejection", "offer",
    "recruiter_outreach", "job_alert", "unrelated",
)
CATEGORY_STATUS = {
    "application_confirmation": "applied",
    "interview_invitation": "interview",
    "rejection": "rejected",
    "offer": "offer",
    "recruiter_outreach": "saved",
}
ACTIONABLE_CATEGORIES = frozenset(CATEGORY_STATUS)
JOB_RELATED_CATEGORIES = ACTIONABLE_CATEGORIES | {"job_alert"}
# Funnel stage used to avoid proposing backwards moves.
STATUS_STAGE = {"saved": 1, "applied": 2, "interview": 3, "offer": 4, "rejected": 5}

ATS_DOMAINS = (
    "greenhouse.io", "greenhouse-mail.io", "lever.co", "ashbyhq.com", "myworkday.com",
    "myworkdayjobs.com", "workday.com", "smartrecruiters.com", "icims.com", "jobvite.com",
    "bamboohr.com", "taleo.net", "successfactors.com", "recruitee.com", "workable.com",
    "workablemail.com", "teamtailor.com", "breezy.hr", "jazzhr.com", "applytojob.com",
    "hackerrank.com", "hackerrankforwork.com", "codility.com", "codesignal.com", "wellfound.com",
    "rippling.com", "dover.com", "gem.com", "personio.de", "zohorecruit.com",
)
JOB_BOARD_DOMAINS = (
    "linkedin.com", "indeed.com", "glassdoor.com", "ziprecruiter.com", "monster.com",
    "naukri.com", "instahyre.com", "foundit.in", "hirist.com", "iimjobs.com", "cutshort.io",
    "wellfound.com", "angel.co", "dice.com", "otta.com", "welcometothejungle.com",
)
GENERIC_MAIL_DOMAINS = (
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "hotmail.com", "outlook.com",
    "live.com", "icloud.com", "me.com", "protonmail.com", "proton.me", "aol.com", "zoho.com",
    "rediffmail.com", "gmx.com", "mail.com", "yandex.com",
)
_TWO_LEVEL_SUFFIXES = ("co.uk", "co.in", "com.au", "co.jp", "com.br", "co.nz", "com.sg", "co.za", "org.uk")

_PREFILTER_SUBJECT = re.compile(
    r"\b(application|applied|applying|interview|offer|position|role|opportunit\w*|candida\w*|"
    r"recruit\w*|hiring|career\w*|job\w*|talent|assessment|next steps?|screen\w*|onsite|"
    r"your (submission|candidacy|profile)|thank you for (your )?(interest|applying)|"
    r"update (on|regarding) your|schedul\w*|availability|hackerrank|codility|codesignal)\b",
    re.IGNORECASE,
)
_PREFILTER_SENDER = re.compile(
    r"(career|job|recruit|talent|hiring|hr@|people@|staffing|acquisition)", re.IGNORECASE
)


def _p(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE)


PATTERNS: dict[str, list[tuple[re.Pattern, float]]] = {
    "rejection": [
        (_p(r"\bunfortunately\b"), 1.0),
        (_p(r"\bnot (?:be )?(?:moving|move) forward\b"), 3),
        (_p(r"\bwill not be (?:moving forward|proceeding|progressing)\b"), 3),
        (_p(r"\b(?:decided|chosen|opted) (?:not to (?:proceed|move forward|progress)|to (?:move forward|proceed|go) with (?:other|another))"), 3),
        (_p(r"\b(?:pursue|pursuing|move forward with|proceed with|progress with) (?:other|another|a different) candidates?\b"), 3),
        (_p(r"\bposition has (?:now )?been filled\b"), 3),
        (_p(r"\bregret to inform\b"), 3),
        (_p(r"\b(?:not|haven'?t|have not) been selected\b"), 3),
        (_p(r"\bno longer (?:being )?consider(?:ed|ing)\b"), 2.5),
        (_p(r"\bafter careful (?:consideration|review)\b"), 1.0),
        (_p(r"\bwe won'?t be (?:moving forward|proceeding)\b"), 3),
        (_p(r"\bnot (?:the right|a) (?:fit|match) (?:at this time|for this role)\b"), 2),
        (_p(r"\bkeep your (?:resume|cv|application|profile) on file\b"), 1.5),
    ],
    "offer": [
        (_p(r"\bpleased to (?:extend|offer)\b"), 3),
        (_p(r"\boffer letter\b"), 3),
        (_p(r"\b(?:extend|extending) (?:you )?(?:an|a formal|a written|a verbal) offer\b"), 3),
        (_p(r"\b(?:job|employment) offer\b"), 2.5),
        (_p(r"\boffer of employment\b"), 3),
        (_p(r"\bcongratulations\b[^.\n]{0,60}\boffer\b"), 3),
        (_p(r"\bcompensation (?:package|details)\b"), 1.5),
        (_p(r"\bformal offer\b"), 3),
        (_p(r"\bwe(?:'d| would) like to offer you\b"), 3),
        (_p(r"\baccept(?:ing)? (?:the|this|our) offer\b"), 2),
    ],
    "interview_invitation": [
        (_p(r"\b(?:schedule|book|set up|arrange) (?:an? |your |the )?(?:interview|call|chat|conversation|meeting|time)\b"), 2.5),
        (_p(r"\binterview (?:invitation|invite|request|availability)\b"), 3),
        (_p(r"\binvite you (?:to|for) (?:an? )?(?:interview|conversation|chat|call)\b"), 3),
        (_p(r"\b(?:phone|technical|onsite|on-site|virtual|video|final|first|second|third|panel|hiring manager|recruiter) (?:screen|interview|round|call)\b"), 2.5),
        (_p(r"\bnext (?:step|round)s?\b"), 1.0),
        (_p(r"\byour availability\b"), 1.5),
        (_p(r"\b(?:calendly|goodtime|cal\.com|modernloop)\b"), 2),
        (_p(r"\b(?:coding|technical|online) (?:challenge|assessment|test|exercise)\b"), 2.5),
        (_p(r"\btake[- ]home (?:assignment|exercise|challenge|project)\b"), 2.5),
        (_p(r"\b(?:hackerrank|codility|codesignal|coderpad|karat)\b"), 2),
        (_p(r"\binterview\b"), 1.0),
    ],
    "application_confirmation": [
        (_p(r"\b(?:thank you|thanks) for (?:applying|your application|submitting your application)\b"), 3),
        (_p(r"\bapplication (?:has been |was )?(?:received|submitted)\b"), 3),
        (_p(r"\bwe(?:'ve| have)? received your application\b"), 3),
        (_p(r"\bapplication (?:confirmation|confirmed)\b"), 3),
        (_p(r"\bsuccessfully (?:applied|submitted)\b"), 2.5),
        (_p(r"\byour application (?:for|to)\b"), 1.5),
        (_p(r"\b(?:thank you|thanks) for (?:your )?interest in\b"), 1.5),
        (_p(r"\bwill (?:review|be reviewing) your (?:application|resume|profile)\b"), 1.5),
    ],
    "recruiter_outreach": [
        (_p(r"\bcame across your (?:profile|resume|background|experience)\b"), 3),
        (_p(r"\bi(?:'m| am) (?:a |the )?(?:technical |senior |lead )?recruiter\b"), 2.5),
        (_p(r"\btalent (?:partner|acquisition|scout)\b"), 1.5),
        (_p(r"\bwould you be (?:open|interested) (?:to|in)\b"), 2),
        (_p(r"\b(?:exciting|great|new) (?:job )?opportunity\b"), 1.0),
        (_p(r"\breach(?:ing)? out (?:about|regarding|to share) (?:an? )?(?:role|position|opportunity|opening)\b"), 2.5),
        (_p(r"\byour (?:profile|background|experience) (?:is|looks|seems) (?:like )?(?:a )?(?:great|strong|perfect|good)\b"), 2),
    ],
    "job_alert": [
        (_p(r"\bjob alerts?\b"), 3),
        (_p(r"\bjobs? (?:you may be interested in|for you|matching your|based on your)\b"), 3),
        (_p(r"\b(?:new|recommended|top) jobs\b"), 2),
        (_p(r"\b\d+\+? new jobs?\b"), 2),
    ],
}
PRECEDENCE = [
    "rejection", "offer", "interview_invitation", "application_confirmation",
    "recruiter_outreach", "job_alert",
]
SUBJECT_WEIGHT = 1.5
MIN_SCORE = 2.0

ROLE_WORDS = re.compile(
    r"\b(engineer|engineering|developer|programmer|scientist|analyst|manager|designer|intern|"
    r"internship|lead|architect|consultant|specialist|associate|administrator|admin|researcher|"
    r"director|officer|coordinator|executive|representative|sde|swe|devops|sre|product|marketing|"
    r"sales|accountant|writer|editor|recruiter|technician|strategist|head of|vp|president|"
    r"fellow|trainee|apprentice|staff|principal|member of technical staff)\b",
    re.IGNORECASE,
)
_COMPANY_JOB_SUFFIX = re.compile(
    r"\s*(?:[-|,@]\s*)?\b(?:recruiting|recruitment|careers?|talent(?: acquisition| team)?|hiring(?: team)?|"
    r"jobs|hr|people(?: team| ops)?|team|no[- ]?reply|notifications?)\b.*$",
    re.IGNORECASE,
)
_CORP_SUFFIX = re.compile(r"[,.]?\s+(?:inc|llc|ltd|limited|corp|corporation|co|gmbh|pvt|private|plc|ag|bv|sa)\.?$", re.IGNORECASE)
# A capitalised name of up to 5 words. Internal dots are allowed ("Booking.com")
# but a trailing sentence period is not ("... at Notion. Please ...").
_NAME_TOKEN = r"[A-Z0-9][\w&'’\-]*(?:\.[A-Za-z0-9][\w&'’\-]*)*"
_NAME_CHARS = rf"{_NAME_TOKEN}(?: (?:&|{_NAME_TOKEN})){{0,4}}"
# Lead-in words are case-insensitive via scoped (?i:...) flags; the captured
# name itself must still start with a capital letter or digit.
_COMPANY_PHRASES = [
    re.compile(rf"(?i:thank you|thanks) (?i:for) (?i:your )?(?i:applying|application|interest) (?i:to|at|in|with) (?i:the team at )?(?P<c>{_NAME_CHARS})"),
    re.compile(rf"(?i:your application) (?i:to|at|with) (?P<c>{_NAME_CHARS})"),
    re.compile(rf"\b(?i:position|role|opportunity|job|opening) (?i:at|with) (?P<c>{_NAME_CHARS})"),
    re.compile(rf"\b(?i:interview) (?i:at|with) (?P<c>{_NAME_CHARS})"),
    re.compile(rf"\b(?i:join|joining) (?i:the team at )?(?P<c>{_NAME_CHARS})(?= as | team|[!.,])"),
    re.compile(rf"\b(?i:from|at) (?P<c>{_NAME_CHARS}) (?:Recruiting|Careers|Talent|Hiring Team|People Team)\b"),
]
_POSITION_PHRASES = [
    re.compile(r"(?i:application|applying|applied) (?i:for|to) (?i:the |our |a )?(?i:position of |role of )?(?P<p>[A-Z][\w/&+.,()\- ]{2,80}?)(?i: position| role| opening)?(?= (?i:at|with) |[!.:\n]| - | – |$)"),
    re.compile(r"\b(?i:for|about|regarding) (?i:the|our|a|an) (?P<p>[A-Z][\w/&+.()\- ]{2,80}?) (?i:position|role|opening|opportunity)\b"),
    re.compile(r"\b(?P<p>[A-Z][\w/&+.()\- ]{2,80}?) (?i:position|role) (?i:at|with) [A-Z]"),
    re.compile(r"\b(?i:interview)[^\n:]{0,25}?(?i:for|:)\s+(?i:the )?(?P<p>[A-Z][\w/&+.()\- ]{2,80}?)(?i: position| role)?(?= (?i:at|with) |[!.,\n]| - |$)"),
    re.compile(r"^(?i:re:\s*|fwd?:\s*)?(?P<p>[A-Z][\w/&+.()\- ]{2,60}?) (?i:at|@) [A-Z]"),
]
_JOB_URL_HINT = re.compile(
    r"(/jobs?/|/careers?/|/positions?/|/openings?/|/apply|greenhouse\.io|lever\.co|ashbyhq\.com|"
    r"myworkdayjobs\.com|smartrecruiters\.com|workable\.com|/vacanc)",
    re.IGNORECASE,
)
_URL_SKIP = re.compile(r"(unsubscribe|optout|opt-out|preferences|privacy|/track|click\.|pixel|beacon)", re.IGNORECASE)
_MONEY = r"(?:\$|usd\s?|₹|inr\s?|rs\.?\s?|€|eur\s?|£|gbp\s?)"
_AMOUNT = r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s?(k|lpa|lakhs?|l)?"
_SALARY_RANGE = re.compile(rf"{_MONEY}\s?{_AMOUNT}\s?(?:-|–|—|to)\s?{_MONEY}?\s?{_AMOUNT}", re.IGNORECASE)


@dataclass
class Classification:
    category: str = "unrelated"
    confidence: float = 0.0
    method: str = "rules"
    company: str | None = None
    position: str | None = None
    location: str | None = None
    job_url: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    applied_date: date | None = None

    @property
    def is_job_related(self) -> bool:
        return self.category in JOB_RELATED_CATEGORIES

    @property
    def is_actionable(self) -> bool:
        return self.category in ACTIONABLE_CATEGORIES

    @property
    def status(self) -> str | None:
        return CATEGORY_STATUS.get(self.category)


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------
def sender_domain(sender_email: str | None) -> str:
    if not sender_email or "@" not in sender_email:
        return ""
    return sender_email.rsplit("@", 1)[1].lower()


def _domain_matches(domain: str, candidates: tuple[str, ...]) -> bool:
    return any(domain == c or domain.endswith("." + c) for c in candidates)


def brand_from_domain(domain: str) -> str | None:
    if not domain or _domain_matches(domain, GENERIC_MAIL_DOMAINS + ATS_DOMAINS + JOB_BOARD_DOMAINS):
        return None
    labels = domain.split(".")
    if len(labels) >= 3 and ".".join(labels[-2:]) in _TWO_LEVEL_SUFFIXES:
        label = labels[-3]
    elif len(labels) >= 2:
        label = labels[-2]
    else:
        return None
    if len(label) < 2 or label.isdigit():
        return None
    if len(label) <= 3:                 # tcs → TCS, ibm → IBM
        return label.upper()
    return label.replace("-", " ").title()


# ---------------------------------------------------------------------------
# Pre-filter (headers only — decides whether a body is worth downloading)
# ---------------------------------------------------------------------------
def prefilter(headers: ParsedHeaders) -> bool:
    domain = sender_domain(headers.sender_email)
    if _domain_matches(domain, ATS_DOMAINS + JOB_BOARD_DOMAINS):
        return True
    if headers.subject and _PREFILTER_SUBJECT.search(headers.subject):
        return True
    sender_blob = f"{headers.sender_name or ''} {headers.sender_email or ''}"
    return bool(_PREFILTER_SENDER.search(sender_blob))


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def score_categories(subject: str, body: str) -> dict[str, float]:
    scores = {}
    for category, patterns in PATTERNS.items():
        total = 0.0
        for pattern, weight in patterns:
            if subject and pattern.search(subject):
                total += weight * SUBJECT_WEIGHT
            elif body and pattern.search(body):
                total += weight
        scores[category] = total
    return scores


def _pick_category(scores: dict[str, float]) -> tuple[str, float, float]:
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], PRECEDENCE.index(kv[0])))
    top_cat, top = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    return top_cat, top, second


def _confidence(top: float, second: float) -> float:
    conf = min(0.95, 0.3 + 0.1 * top)
    if second >= 0.75 * top:          # ambiguous — two categories nearly tied
        conf -= 0.2
    return round(max(0.2, conf), 2)


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------
def _appears_in(value: str, haystack: str) -> bool:
    return bool(value) and re.sub(r"\s+", " ", value).casefold() in re.sub(r"\s+", " ", haystack).casefold()


def _clean_company(raw: str | None) -> str | None:
    if not raw:
        return None
    s = re.sub(r"\s+", " ", raw).strip(" -–|,.:;!\"'")
    s = _COMPANY_JOB_SUFFIX.sub("", s).strip(" -–|,.:;")
    s = _CORP_SUFFIX.sub("", s).strip(" -–|,.")
    if not s or len(s) < 2 or len(s) > 80 or "@" in s:
        return None
    if s.lower() in {"the", "our", "us", "we", "team", "you", "your", "a", "an", "this", "the team"}:
        return None
    return s


def extract_company(p: ParsedEmail | ParsedHeaders, body: str = "") -> str | None:
    subject = p.subject or ""
    name = p.sender_name or ""
    domain = sender_domain(p.sender_email)
    haystack = f"{name} {p.sender_email or ''} {subject} {body}"

    candidates: list[str | None] = []
    for pattern in _COMPANY_PHRASES:                         # 1. explicit phrase in subject
        if (m := pattern.search(subject)):
            candidates.append(m.group("c"))
    if name and _COMPANY_JOB_SUFFIX.search(name):            # 2. "Stripe Recruiting"
        candidates.append(name)
    if name and _domain_matches(domain, ATS_DOMAINS):        # 3. ATS mail: display name is the company
        candidates.append(name)
    for pattern in _COMPANY_PHRASES:                         # 4. explicit phrase in body
        if (m := pattern.search(body[:3000])):
            candidates.append(m.group("c"))
    candidates.append(brand_from_domain(domain))             # 5. corporate sender domain

    for candidate in candidates:
        company = _clean_company(candidate)
        if company and (_appears_in(company, haystack) or _appears_in(company.replace(" ", ""), haystack)):
            return company
    return None


def extract_position(subject: str, body: str) -> str | None:
    for text in (subject or "", (body or "")[:3000]):
        for pattern in _POSITION_PHRASES:
            m = pattern.search(text)
            if not m:
                continue
            pos = re.sub(r"\s+", " ", m.group("p")).strip(" -–|,.:;")
            pos = re.sub(r"^(?:the|our|a|an)\s+", "", pos, flags=re.IGNORECASE)
            if 2 < len(pos) <= 120 and ROLE_WORDS.search(pos):
                return pos
    return None


def extract_job_url(urls: list[str]) -> str | None:
    for url in urls:
        if not url.lower().startswith(("https://", "http://")):
            continue
        if _URL_SKIP.search(url):
            continue
        if _JOB_URL_HINT.search(url) and len(url) <= 500:
            return url
    return None


def _to_amount(number: str, unit: str | None) -> int | None:
    try:
        value = float(number.replace(",", ""))
    except ValueError:
        return None
    unit = (unit or "").lower()
    if unit == "k":
        value *= 1_000
    elif unit in ("lpa", "l", "lakh", "lakhs"):
        value *= 100_000
    return int(value) if 0 < value < 1_000_000_000 else None


def extract_salary(text: str) -> tuple[int | None, int | None]:
    m = _SALARY_RANGE.search(text or "")
    if not m:
        return None, None
    low = _to_amount(m.group(1), m.group(2) or m.group(4))
    high = _to_amount(m.group(3), m.group(4) or m.group(2))
    if low is None or high is None or high < low:
        return None, None
    return low, high


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def classify(parsed: ParsedEmail, received: date | None = None) -> Classification:
    subject = parsed.subject or ""
    body = parsed.body_text or ""
    scores = score_categories(subject, body)
    category, top, second = _pick_category(scores)
    if top < MIN_SCORE:
        return Classification(category="unrelated", confidence=round(min(0.5, 0.2 + 0.1 * top), 2))

    result = Classification(category=category, confidence=_confidence(top, second))
    if category not in ACTIONABLE_CATEGORIES:
        return result

    salary_min, salary_max = extract_salary(f"{subject}\n{body}")
    return replace(
        result,
        company=extract_company(parsed, body),
        position=extract_position(subject, body),
        job_url=extract_job_url(parsed.urls),
        salary_min=salary_min,
        salary_max=salary_max,
        applied_date=received if category == "application_confirmation" else None,
    )


# ---------------------------------------------------------------------------
# Company normalisation for matching against existing jobs
# ---------------------------------------------------------------------------
def normalize_company(name: str | None) -> str:
    if not name:
        return ""
    s = name.casefold().strip()
    s = re.sub(r"[^\w\s&]", " ", s)
    for _ in range(2):
        s = _CORP_SUFFIX.sub("", s.strip())
    return re.sub(r"\s+", " ", s).strip()
