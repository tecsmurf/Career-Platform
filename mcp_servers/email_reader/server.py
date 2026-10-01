"""
Email MCP Server — Reads emails and extracts job-related updates
================================================================

This MCP server connects to your email (Gmail via IMAP) and provides tools to:
1. Fetch recent emails
2. Search emails by sender/subject
3. Get full email content
4. Extract job-related signals (interview, rejection, offer, etc.)

MCP Tools exposed:
    - fetch_recent_emails     → Get latest N emails
    - search_emails           → Search by keyword, sender, date range
    - get_email_content       → Read full email body
    - scan_job_emails         → AI-powered: find job-related emails and extract status signals
"""
import json
import asyncio
import email
import imaplib
import os
import re
import ssl
from datetime import datetime, timedelta
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

server = Server("email-reader")

# ============================================================
# EMAIL CONNECTION
# ============================================================
# Gmail IMAP requires an "App Password" (not your regular password)
# Go to: Google Account → Security → 2FA → App Passwords → Generate
EMAIL_HOST = os.getenv("EMAIL_HOST", "imap.gmail.com")
EMAIL_USER = os.getenv("EMAIL_USER", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")  # Gmail App Password


IMAP_TIMEOUT = int(os.getenv("EMAIL_IMAP_TIMEOUT", "15"))


def get_imap_connection():
    """Connect to email via IMAP over *verified* TLS, with a timeout.

    imaplib's default SSL context does not verify certificates, so an explicit
    default context (CERT_REQUIRED + hostname check) is always passed.
    """
    if not EMAIL_USER or not EMAIL_PASSWORD:
        raise ValueError("EMAIL_USER and EMAIL_PASSWORD environment variables are required")
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    mail = imaplib.IMAP4_SSL(EMAIL_HOST, ssl_context=ctx, timeout=IMAP_TIMEOUT)
    mail.login(EMAIL_USER, EMAIL_PASSWORD)
    return mail


def _decode_part(data: bytes, charset: str | None) -> str:
    """Declared charset if it exists; otherwise strict UTF-8, then Latin-1 (never fails)."""
    if charset:
        try:
            return data.decode(charset, errors="replace")
        except LookupError:
            pass
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _imap_quote(value: str) -> str:
    """Quote a user-supplied IMAP search string (prevents search-syntax injection)."""
    cleaned = re.sub(r"[\r\n\x00]", " ", value or "")
    return '"' + cleaned.replace("\\", "\\\\").replace('"', '\\"') + '"'


def parse_email(raw_email: bytes) -> dict:
    """Parse a raw email into a structured dict."""
    msg = email.message_from_bytes(raw_email)
    
    # Decode subject
    subject = ""
    if msg["Subject"]:
        decoded = email.header.decode_header(msg["Subject"])
        subject = "".join(
            _decode_part(part, enc) if isinstance(part, bytes) else part
            for part, enc in decoded
        )
    
    # Get body
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    body = _decode_part(payload, part.get_content_charset())
                    break
            elif content_type == "text/html" and not body:
                payload = part.get_payload(decode=True)
                if payload:
                    # Strip HTML tags for plain text
                    html = _decode_part(payload, part.get_content_charset())
                    body = re.sub(r'<[^>]+>', ' ', html)
                    body = re.sub(r'\s+', ' ', body).strip()
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body = _decode_part(payload, msg.get_content_charset())
    
    # Parse date
    date_str = msg.get("Date", "")
    
    return {
        "subject": subject,
        "from": msg.get("From", ""),
        "to": msg.get("To", ""),
        "date": date_str,
        "body": body[:3000],  # Limit body size
        "message_id": msg.get("Message-ID", ""),
    }


# ============================================================
# JOB EMAIL DETECTION
# ============================================================
# Keywords that indicate job-related emails and their likely status
JOB_SIGNAL_PATTERNS = {
    "interview": [
        r"schedule.*interview",
        r"interview.*invite",
        r"like to (schedule|set up|arrange).*call",
        r"phone screen",
        r"technical interview",
        r"onsite interview",
        r"virtual interview",
        r"next step.*interview",
        r"coding challenge",
        r"assessment",
        r"hiring manager.*meet",
    ],
    "offer": [
        r"pleased to offer",
        r"offer letter",
        r"congratulations.*offer",
        r"compensation package",
        r"start date",
        r"we.*(would|'d) like to (offer|extend)",
        r"formal offer",
    ],
    "rejected": [
        r"unfortunately.*not.*moving forward",
        r"decided.*not.*proceed",
        r"other candidates",
        r"not.*selected",
        r"position.*filled",
        r"regret to inform",
        r"will not be moving forward",
        r"after careful consideration.*unable",
    ],
    "applied": [
        r"application.*received",
        r"thank.*for applying",
        r"we.*received.*application",
        r"application.*confirmed",
    ],
}


def detect_job_signal(subject: str, body: str) -> dict | None:
    """
    Detect if an email is job-related and what status it signals.
    
    Returns: {"status": "interviewing", "confidence": "high", "matched_pattern": "..."}
    or None if not job-related.
    """
    text = f"{subject} {body}".lower()
    
    for status, patterns in JOB_SIGNAL_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return {
                    "detected_status": status,
                    "confidence": "high",
                    "matched_pattern": pattern,
                }
    
    # Check for generic job-related keywords
    job_keywords = ["position", "role", "opportunity", "application", "candidate", "hiring", "recruiter"]
    if any(kw in text for kw in job_keywords):
        return {
            "detected_status": "unknown",
            "confidence": "low",
            "matched_pattern": "generic job keywords",
        }
    
    return None


def extract_company_from_email(from_addr: str, subject: str, body: str) -> str | None:
    """Try to extract the company name from email metadata."""
    # From the sender domain
    domain_match = re.search(r'@([a-zA-Z0-9.-]+)\.[a-zA-Z]+', from_addr)
    if domain_match:
        domain = domain_match.group(1)
        # Skip generic email providers
        generic = ["gmail", "yahoo", "hotmail", "outlook", "protonmail", "icloud"]
        if domain.lower() not in generic:
            return domain.replace(".", " ").title()
    
    # From common patterns in subject/body
    patterns = [
        r"(?:at|from|with)\s+([A-Z][A-Za-z0-9\s&]+?)(?:\s*[,.\-!]|\s+for\s+)",
        r"([A-Z][A-Za-z0-9\s&]+?)\s+(?:is|has|would)",
    ]
    for pattern in patterns:
        match = re.search(pattern, subject + " " + body[:500])
        if match:
            company = match.group(1).strip()
            if 3 < len(company) < 50:
                return company
    
    return None


# ============================================================
# MCP TOOL DEFINITIONS
# ============================================================
@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="fetch_recent_emails",
            description="Fetch the most recent emails from inbox. Returns subject, sender, date, and preview.",
            inputSchema={
                "type": "object",
                "properties": {
                    "count": {"type": "integer", "description": "Number of emails to fetch (default 20)", "default": 20},
                    "folder": {"type": "string", "description": "Email folder (default INBOX)", "default": "INBOX"},
                },
            },
        ),
        Tool(
            name="search_emails",
            description="Search emails by keyword in subject/body, sender, or date range.",
            inputSchema={
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "Search term (searches subject and body)"},
                    "sender": {"type": "string", "description": "Filter by sender email/name"},
                    "days_back": {"type": "integer", "description": "How many days back to search (default 30)", "default": 30},
                },
            },
        ),
        Tool(
            name="get_email_content",
            description="Get the full content of a specific email by its message ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "message_id": {"type": "string", "description": "Email message ID"},
                },
                "required": ["message_id"],
            },
        ),
        Tool(
            name="scan_job_emails",
            description="Scan recent emails for job-related updates (interviews, offers, rejections). Uses pattern matching to detect job signals and extract company names.",
            inputSchema={
                "type": "object",
                "properties": {
                    "days_back": {"type": "integer", "description": "How many days back to scan (default 7)", "default": 7},
                    "count": {"type": "integer", "description": "Max emails to scan (default 50)", "default": 50},
                },
            },
        ),
    ]


# ============================================================
# MCP TOOL IMPLEMENTATIONS
# ============================================================
@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    try:
        if name == "fetch_recent_emails":
            result = _fetch_recent(arguments.get("count", 20), arguments.get("folder", "INBOX"))
        elif name == "search_emails":
            result = _search_emails(
                arguments.get("keyword"), arguments.get("sender"), arguments.get("days_back", 30)
            )
        elif name == "get_email_content":
            result = _get_email_content(arguments["message_id"])
        elif name == "scan_job_emails":
            result = _scan_job_emails(arguments.get("days_back", 7), arguments.get("count", 50))
        else:
            result = {"error": f"Unknown tool: {name}"}
        
        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


def _fetch_recent(count: int, folder: str) -> list[dict]:
    """Fetch recent emails."""
    mail = get_imap_connection()
    try:
        mail.select(folder, readonly=True)
        _, data = mail.search(None, "ALL")
        email_ids = data[0].split()
        
        # Get the last N emails
        recent_ids = email_ids[-count:]
        recent_ids.reverse()  # Newest first
        
        emails = []
        for eid in recent_ids:
            _, msg_data = mail.fetch(eid, "(BODY.PEEK[])")
            if msg_data[0] is None:
                continue
            parsed = parse_email(msg_data[0][1])
            parsed["body"] = parsed["body"][:300]  # Preview only
            emails.append(parsed)
        
        return emails
    finally:
        mail.logout()


def _search_emails(keyword: str = None, sender: str = None, days_back: int = 30) -> list[dict]:
    """Search emails with filters."""
    mail = get_imap_connection()
    try:
        mail.select("INBOX", readonly=True)
        
        # Build IMAP search criteria
        criteria = []
        if keyword:
            criteria.append(f"(OR SUBJECT {_imap_quote(keyword)} BODY {_imap_quote(keyword)})")
        if sender:
            criteria.append(f"FROM {_imap_quote(sender)}")
        if days_back:
            since_date = (datetime.now() - timedelta(days=days_back)).strftime("%d-%b-%Y")
            criteria.append(f'SINCE {since_date}')
        
        search_str = " ".join(criteria) if criteria else "ALL"
        _, data = mail.search(None, search_str)
        email_ids = data[0].split()
        
        emails = []
        for eid in email_ids[-50:]:  # Cap at 50
            _, msg_data = mail.fetch(eid, "(BODY.PEEK[])")
            if msg_data[0] is None:
                continue
            parsed = parse_email(msg_data[0][1])
            parsed["body"] = parsed["body"][:500]
            emails.append(parsed)
        
        emails.reverse()  # Newest first
        return emails
    finally:
        mail.logout()


def _get_email_content(message_id: str) -> dict:
    """Get full email by message ID."""
    mail = get_imap_connection()
    try:
        mail.select("INBOX", readonly=True)
        _, data = mail.search(None, f"HEADER Message-ID {_imap_quote(message_id)}")
        email_ids = data[0].split()
        
        if not email_ids:
            return {"error": "Email not found"}
        
        _, msg_data = mail.fetch(email_ids[0], "(BODY.PEEK[])")
        return parse_email(msg_data[0][1])
    finally:
        mail.logout()


def _scan_job_emails(days_back: int, count: int) -> list[dict]:
    """
    Scan emails for job-related updates.
    
    This is the KEY function — it:
    1. Fetches recent emails
    2. Detects if each is job-related
    3. Extracts: status signal, company name, confidence
    
    Returns only job-related emails with their detected signals.
    """
    mail = get_imap_connection()
    try:
        mail.select("INBOX", readonly=True)
        
        since_date = (datetime.now() - timedelta(days=days_back)).strftime("%d-%b-%Y")
        _, data = mail.search(None, f'SINCE {since_date}')
        email_ids = data[0].split()
        
        # Process the most recent emails
        recent_ids = email_ids[-count:]
        recent_ids.reverse()
        
        job_emails = []
        for eid in recent_ids:
            _, msg_data = mail.fetch(eid, "(BODY.PEEK[])")
            if msg_data[0] is None:
                continue
            
            parsed = parse_email(msg_data[0][1])
            signal = detect_job_signal(parsed["subject"], parsed["body"])
            
            if signal:
                company = extract_company_from_email(parsed["from"], parsed["subject"], parsed["body"])
                job_emails.append({
                    "subject": parsed["subject"],
                    "from": parsed["from"],
                    "date": parsed["date"],
                    "body_preview": parsed["body"][:500],
                    "message_id": parsed["message_id"],
                    "job_signal": signal,
                    "detected_company": company,
                })
        
        return {
            "total_scanned": len(recent_ids),
            "job_related_found": len(job_emails),
            "job_emails": job_emails,
        }
    finally:
        mail.logout()


# ============================================================
# RUN SERVER
# ============================================================
async def main():
    from mcp.types import ServerCapabilities
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )

if __name__ == "__main__":
    asyncio.run(main())
