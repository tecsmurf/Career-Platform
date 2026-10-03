"""
Transactional email through Brevo's HTTPS API.

Render's free tier blocks outbound SMTP (ports 25/465/587), so account email
(verification and password-reset codes) goes out over HTTPS instead:

    POST https://api.brevo.com/v3/smtp/email
    api-key: <BREVO_API_KEY>
    {"sender": {...}, "to": [...], "subject": ..., "htmlContent": ..., "textContent": ...}
    → 201 {"messageId": "<...>"}

The API key is sent only in that header. It never appears in logs, exception
messages or responses; failures are reported as ``MailerError`` with a
user-safe message, and only the HTTP status / Brevo error code is logged.
"""
from __future__ import annotations

import html
import logging
from dataclasses import dataclass

import httpx

from app.core.config import settings

logger = logging.getLogger("app.mailer")


class MailerError(Exception):
    """The message was not accepted by the provider. The text is safe to show."""


@dataclass(frozen=True)
class OutgoingEmail:
    to_email: str
    subject: str
    html: str
    text: str


class BrevoMailer:
    def __init__(
        self,
        *,
        api_key: str,
        sender_email: str,
        sender_name: str,
        api_url: str = "https://api.brevo.com/v3/smtp/email",
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._sender = {"email": sender_email, "name": sender_name}
        self._url = api_url
        self._timeout = timeout
        self._transport = transport

    def __repr__(self) -> str:  # never show the key, even in a debugger or traceback
        return f"BrevoMailer(sender={self._sender['email']!r})"

    async def send(self, message: OutgoingEmail) -> str:
        payload = {
            "sender": self._sender,
            "to": [{"email": message.to_email}],
            "subject": message.subject,
            "htmlContent": message.html,
            "textContent": message.text,
        }
        headers = {"api-key": self._api_key, "accept": "application/json", "content-type": "application/json"}
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=self._timeout) as client:
                response = await client.post(self._url, json=payload, headers=headers)
        except httpx.TimeoutException:
            logger.warning("mail.send_failed reason=timeout")
            raise MailerError("The email service did not respond in time.") from None
        except httpx.HTTPError as exc:
            logger.warning("mail.send_failed reason=%s", type(exc).__name__)
            raise MailerError("The email service could not be reached.") from None

        if response.status_code in (200, 201, 202):
            try:
                body = response.json()
            except ValueError:
                body = None
            message_id = str(body.get("messageId") or "") if isinstance(body, dict) else ""
            logger.info("mail.sent status=%s", response.status_code)
            return message_id

        try:
            body = response.json()
        except ValueError:
            body = None
        code = str(body.get("code") or "")[:60] if isinstance(body, dict) else ""
        logger.warning("mail.send_failed status=%s provider_code=%s", response.status_code, code or "-")
        if response.status_code in (401, 403):
            raise MailerError("The email service rejected the server's credentials.")
        if response.status_code == 429:
            raise MailerError("The email service is rate-limiting us. Please try again later.")
        raise MailerError("The email service did not accept the message.")


def get_mailer() -> BrevoMailer | None:
    """FastAPI dependency: the configured mailer, or None when account email is off.

    Tests override this dependency with a fake.
    """
    if not settings.email_auth_active:
        return None
    return BrevoMailer(
        api_key=settings.BREVO_API_KEY.strip(),
        sender_email=settings.MAIL_FROM_ADDRESS.strip(),
        sender_name=settings.MAIL_FROM_NAME.strip() or "Career Platform",
        api_url=settings.BREVO_API_URL,
        timeout=settings.MAIL_TIMEOUT_SECONDS,
    )


# ---------------------------------------------------------------------------
# Message bodies (white + sky-blue, inline styles for mail clients)
# ---------------------------------------------------------------------------
_TEMPLATES = {
    "verify_email": {
        "subject": "{code} is your Career Platform verification code",
        "heading": "Verify your email",
        "intro": "Use this code to finish setting up your Career Platform account.",
        "outro": "If you didn't create an account, you can ignore this email.",
    },
    "reset_password": {
        "subject": "{code} is your Career Platform password reset code",
        "heading": "Reset your password",
        "intro": "Use this code to choose a new password for your Career Platform account.",
        "outro": "If you didn't ask to reset your password, ignore this email — your password stays the same.",
    },
}


def build_code_email(*, purpose: str, code: str, to_email: str, ttl_minutes: int) -> OutgoingEmail:
    # Deliberately no user-supplied text (not even the name): sign-up emails go
    # to addresses nobody has verified yet, so anything the registrant typed
    # would let the form be used to send arbitrary text from our sender.
    t = _TEMPLATES[purpose]
    greeting = "Hi,"
    expiry = f"The code expires in {ttl_minutes} minutes and can be used once."
    text = "\n\n".join([greeting, t["intro"], f"Your code: {code}", expiry, t["outro"], "— Career Platform"])
    e = html.escape
    html_body = f"""<!doctype html>
<html><body style="margin:0;padding:0;background:#f0f9ff;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#0f172a">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f0f9ff;padding:32px 12px">
<tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:480px;background:#ffffff;border:1px solid #bae6fd;border-radius:16px">
<tr><td style="padding:28px 28px 8px">
<div style="font-size:15px;font-weight:700;color:#0284c7;letter-spacing:-0.01em">Career Platform</div>
<h1 style="margin:14px 0 6px;font-size:21px;line-height:1.3;color:#0f172a">{e(t["heading"])}</h1>
<p style="margin:0 0 4px;font-size:15px;line-height:1.55;color:#334155">{e(greeting)}</p>
<p style="margin:0;font-size:15px;line-height:1.55;color:#334155">{e(t["intro"])}</p>
</td></tr>
<tr><td style="padding:18px 28px">
<div style="background:#f0f9ff;border:1px solid #7dd3fc;border-radius:12px;padding:16px;text-align:center;font-size:32px;font-weight:700;letter-spacing:8px;color:#0369a1;font-family:SFMono-Regular,Consolas,Menlo,monospace">{e(code)}</div>
<p style="margin:12px 0 0;font-size:13px;line-height:1.5;color:#64748b">{e(expiry)}</p>
</td></tr>
<tr><td style="padding:4px 28px 26px">
<p style="margin:0;font-size:13px;line-height:1.5;color:#64748b">{e(t["outro"])}</p>
</td></tr>
</table>
</td></tr></table>
</body></html>"""
    return OutgoingEmail(
        to_email=to_email,
        subject=t["subject"].format(code=code),
        html=html_body,
        text=text,
    )
