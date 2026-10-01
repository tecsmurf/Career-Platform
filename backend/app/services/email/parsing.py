"""
Email parsing & normalisation — email content is UNTRUSTED input.
=================================================================

- Never raises on malformed MIME, bad base64/quoted-printable or unknown
  charsets: every step degrades gracefully.
- Attachments are skipped; only text/plain and text/html parts are read.
- HTML is converted to plain text (script/style/head/iframe/svg content
  dropped, entities decoded). HTML is never stored or rendered.
- Control characters and bidi/zero-width characters are stripped from all
  text (prevents header-injection weirdness and visual spoofing in the UI).
- Output sizes are bounded.
"""
import email
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.header import decode_header
from email.policy import compat32
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from html.parser import HTMLParser

MAX_BODY_CHARS = 20_000
SNIPPET_CHARS = 280
MAX_SUBJECT = 500
MAX_URLS = 50

_CTRL_INLINE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_CTRL_BODY = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_INVISIBLE = re.compile(r"[​-‏‪-‮⁠-⁤⁦-⁩﻿­]")
_URL_RE = re.compile(r"https?://[^\s<>\"'`\)\]\}]+", re.IGNORECASE)
_SIMPLE_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}$")


@dataclass
class ParsedHeaders:
    message_id: str | None
    subject: str
    sender_name: str | None
    sender_email: str | None
    recipients: str | None
    date: datetime | None
    list_id: str | None
    has_list_unsubscribe: bool


@dataclass
class ParsedEmail(ParsedHeaders):
    body_text: str = ""
    urls: list[str] = field(default_factory=list)

    @property
    def snippet(self) -> str:
        return make_snippet(self.body_text)


# ---------------------------------------------------------------------------
# Text cleaning
# ---------------------------------------------------------------------------
def clean_inline(value: str, limit: int | None = None) -> str:
    s = _INVISIBLE.sub("", value or "")
    s = _CTRL_INLINE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit] if limit else s


def clean_body(value: str) -> str:
    s = (value or "").replace("\r\n", "\n").replace("\r", "\n")
    s = _INVISIBLE.sub("", s)
    s = _CTRL_BODY.sub("", s)
    s = s.replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in s.split("\n")]
    s = "\n".join(lines)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s[:MAX_BODY_CHARS]


def make_snippet(body: str) -> str:
    s = re.sub(r"\s+", " ", body or "").strip()
    return s[:SNIPPET_CHARS]


def decode_bytes(data: bytes, charset: str | None) -> str:
    """Declared charset if it exists; otherwise strict UTF-8, then Latin-1 (never fails)."""
    if charset:
        try:
            return data.decode(charset, errors="replace")
        except (LookupError, TypeError):
            pass
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def decode_header_value(value) -> str:
    if value is None:
        return ""
    try:
        parts = decode_header(str(value))
        out = []
        for chunk, enc in parts:
            out.append(decode_bytes(chunk, enc) if isinstance(chunk, bytes) else str(chunk))
        text = "".join(out)
    except Exception:
        text = str(value)
    return clean_inline(text)


# ---------------------------------------------------------------------------
# HTML → text
# ---------------------------------------------------------------------------
class _HTMLToText(HTMLParser):
    SKIP = {"script", "style", "head", "title", "noscript", "template", "svg", "iframe", "object", "embed", "math"}
    BLOCK = {
        "p", "div", "br", "li", "ul", "ol", "tr", "table", "section", "article", "header",
        "footer", "blockquote", "hr", "h1", "h2", "h3", "h4", "h5", "h6", "pre",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "a" and not self._skip:
            for name, val in attrs:
                if name and name.lower() == "href" and val and val.lower().startswith(("http://", "https://")):
                    self.links.append(val.strip())

    def handle_startendtag(self, tag, attrs):
        if tag.lower() in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> tuple[str, list[str]]:
    parser = _HTMLToText()
    try:
        parser.feed(html or "")
        parser.close()
    except Exception:
        pass
    return "".join(parser.parts), parser.links


# ---------------------------------------------------------------------------
# Headers
# ---------------------------------------------------------------------------
def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except Exception:
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def normalize_message_id(raw: str | None) -> str | None:
    if not raw:
        return None
    mid = clean_inline(str(raw)).strip().strip("<>").strip()
    return mid[:500] or None


def message_key(message_id: str | None, fallback: str) -> str:
    """Stable dedup key: sha256 of the Message-ID, else of the mailbox identity."""
    basis = f"mid:{message_id}" if message_id else f"fallback:{fallback}"
    return hashlib.sha256(basis.encode("utf-8", "replace")).hexdigest()


def _headers_from_message(msg) -> ParsedHeaders:
    subject = decode_header_value(msg.get("Subject"))[:MAX_SUBJECT]
    name, addr = parseaddr(decode_header_value(msg.get("From")))
    addr = (addr or "").strip().lower()
    sender_email = addr if _SIMPLE_EMAIL.match(addr) and len(addr) <= 320 else None
    sender_name = clean_inline(name, 255) or None
    try:
        tos = getaddresses([decode_header_value(v) for v in msg.get_all("To", [])])
        recipients = clean_inline(", ".join(a for _, a in tos if a), 500) or None
    except Exception:
        recipients = None
    return ParsedHeaders(
        message_id=normalize_message_id(msg.get("Message-ID")),
        subject=subject,
        sender_name=sender_name,
        sender_email=sender_email,
        recipients=recipients,
        date=_parse_date(msg.get("Date")),
        list_id=clean_inline(decode_header_value(msg.get("List-Id")), 255) or None,
        has_list_unsubscribe=bool(msg.get("List-Unsubscribe")),
    )


def parse_headers(raw_headers: bytes) -> ParsedHeaders:
    try:
        msg = email.message_from_bytes(raw_headers or b"", policy=compat32)
    except Exception:
        msg = email.message_from_bytes(b"", policy=compat32)
    return _headers_from_message(msg)


# ---------------------------------------------------------------------------
# Full message
# ---------------------------------------------------------------------------
def parse_message(raw: bytes) -> ParsedEmail:
    try:
        msg = email.message_from_bytes(raw or b"", policy=compat32)
    except Exception:
        msg = email.message_from_bytes(b"", policy=compat32)

    headers = _headers_from_message(msg)
    plain: list[str] = []
    html: list[str] = []
    budget = MAX_BODY_CHARS * 4
    try:
        for part in msg.walk():
            if part.is_multipart():
                continue
            disposition = str(part.get("Content-Disposition") or "").lower()
            if "attachment" in disposition:
                continue
            ctype = (part.get_content_type() or "").lower()
            if ctype not in ("text/plain", "text/html"):
                continue
            try:
                payload = part.get_payload(decode=True)
            except Exception:
                continue
            if not payload:
                continue
            text = decode_bytes(payload[:budget], part.get_content_charset())
            (plain if ctype == "text/plain" else html).append(text)
            budget -= len(payload)
            if budget <= 0:
                break
    except Exception:
        pass

    links: list[str] = []
    if plain:
        body = "\n\n".join(plain)
    elif html:
        body, links = html_to_text("\n".join(html))
    else:
        body = ""
    body = clean_body(body)

    urls = []
    for u in links + _URL_RE.findall(body):
        u = u.rstrip(".,;:!?'\"")
        if 10 <= len(u) <= 500 and u not in urls:
            urls.append(u)
        if len(urls) >= MAX_URLS:
            break

    return ParsedEmail(**headers.__dict__, body_text=body, urls=urls)


def effective_received_at(internal_date: datetime | None, header_date: datetime | None) -> datetime | None:
    """Prefer the server's INTERNALDATE; never return a far-future date."""
    dt = internal_date or header_date
    if dt is None:
        return None
    now = datetime.now(timezone.utc)
    return min(dt, now + timedelta(hours=1))
