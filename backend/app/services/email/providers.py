"""
Email providers
===============

    EmailProvider (base: IMAP over verified TLS, port 993)
        ├── GmailIMAPProvider    fixed host imap.gmail.com, App Password only
        └── GenericIMAPProvider  any public IMAP host the user supplies

Adding a provider = subclass + register in PROVIDERS. Provider-specific rules
(fixed host, credential format, help text, error wording) live here and
nowhere else.
"""
import re

from app.services.email import imap_client
from app.services.email.errors import AuthenticationFailed, InvalidAccountDetails
from app.services.email.imap_client import MailboxAccount, MailboxSession
from app.services.email.network import normalize_hostname

_EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")
_MAX_PASSWORD = 512


def normalize_email_address(value: str) -> str:
    email = (value or "").strip().lower()
    if len(email) > 320 or not _EMAIL_RE.match(email):
        raise InvalidAccountDetails("Enter a valid email address.")
    return email


class EmailProvider:
    id: str = "base"
    name: str = "Email"
    fixed_host: str | None = None
    port: int = 993
    auth_failed_message: str = AuthenticationFailed.default_message

    @property
    def requires_host(self) -> bool:
        return self.fixed_host is None

    def normalize_password(self, password: str) -> str:
        pw = password or ""
        if not pw.strip():
            raise InvalidAccountDetails("Enter your app password.")
        if len(pw) > _MAX_PASSWORD:
            raise InvalidAccountDetails("That password is too long.")
        return pw

    def resolve_host(self, host: str | None) -> str:
        if self.fixed_host:
            return self.fixed_host
        return normalize_hostname(host or "")

    def build_account(self, *, email: str, password: str, host: str | None = None) -> MailboxAccount:
        address = normalize_email_address(email)
        pw = self.normalize_password(password)
        resolved_host = self.resolve_host(host)
        try:
            return MailboxAccount(host=resolved_host, port=self.port, username=address, password=pw)
        except ValueError:
            raise InvalidAccountDetails("Credentials contain characters that aren't allowed.") from None

    def open(self, account: MailboxAccount, timeout: float) -> MailboxSession:
        try:
            return imap_client.open_session(account, timeout)
        except AuthenticationFailed:
            raise AuthenticationFailed(self.auth_failed_message) from None

    def verify(self, account: MailboxAccount, timeout: float, mailbox: str = "INBOX") -> None:
        """Blocking: prove the credentials work (login + read-only mailbox open)."""
        session = self.open(account, timeout)
        try:
            session.select_readonly(mailbox)
        finally:
            session.close()

    def public_info(self) -> dict:
        return {"id": self.id, "name": self.name, "fixed_host": self.fixed_host, "requires_host": self.requires_host}


class GmailIMAPProvider(EmailProvider):
    id = "gmail"
    name = "Gmail"
    fixed_host = "imap.gmail.com"
    auth_failed_message = (
        "Google rejected this login. Use a 16-character App Password (not your normal "
        "Google password) and make sure IMAP access is enabled in Gmail settings."
    )
    _APP_PASSWORD = re.compile(r"^[A-Za-z]{16}$")

    def normalize_password(self, password: str) -> str:
        # Google displays app passwords in groups of four ("abcd efgh ijkl mnop").
        compact = re.sub(r"\s+", "", password or "")
        if not self._APP_PASSWORD.match(compact):
            # Refuse to send anything that isn't an app password — we never want
            # a user's real Google account password on the wire or in storage.
            raise InvalidAccountDetails(
                "That doesn't look like a Gmail App Password. App passwords are 16 letters, "
                "generated at myaccount.google.com/apppasswords."
            )
        return compact


class GenericIMAPProvider(EmailProvider):
    id = "imap"
    name = "IMAP mailbox"
    auth_failed_message = (
        "Your mail server rejected these credentials. Check the address, IMAP host and "
        "password (many providers require an app-specific password for IMAP)."
    )


PROVIDERS: dict[str, EmailProvider] = {
    GmailIMAPProvider.id: GmailIMAPProvider(),
    GenericIMAPProvider.id: GenericIMAPProvider(),
}


def get_provider(provider_id: str) -> EmailProvider:
    provider = PROVIDERS.get((provider_id or "").strip().lower())
    if provider is None:
        raise InvalidAccountDetails("Unsupported email provider.")
    return provider
