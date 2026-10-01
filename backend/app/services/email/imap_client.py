"""
IMAP transport (blocking — always call from a worker thread, never the event loop).
==================================================================================

Safety properties:
- TLS certificate AND host name are verified (ssl.create_default_context, TLS>=1.2).
  imaplib's own default is an *unverified* context, so we never rely on it.
- The TCP connection goes to the IP pinned by network.resolve_public_address;
  the certificate is still checked against the host name (SNI).
- One socket timeout covers connect, TLS handshake, LOGIN and every command.
- Mailboxes are opened read-only (EXAMINE) and bodies are fetched with
  BODY.PEEK, so syncing never changes flags (never marks mail as read).
- Only the first N bytes of a message are downloaded (attachments beyond that
  are never transferred).
- Server / library error text is never propagated to callers.
"""
import imaplib
import re
import socket
import ssl
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from app.services.email.errors import (
    AuthenticationFailed, EmailProviderError, MailboxError, ProviderTimeout,
    ProviderUnavailable, TLSVerificationFailed,
)
from app.services.email.network import resolve_public_address

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_MONTH_INDEX = {m.lower(): i + 1 for i, m in enumerate(_MONTHS)}
_FORBIDDEN_CHARS = re.compile(r"[\r\n\x00]")

_FETCH_START = re.compile(rb"^(\d+) \(")
_UID_RE = re.compile(rb"\bUID (\d+)")
_SIZE_RE = re.compile(rb"\bRFC822\.SIZE (\d+)")
_INTERNALDATE_RE = re.compile(rb'\bINTERNALDATE "([^"]+)"')
_THRID_RE = re.compile(rb"\bX-GM-THRID (\d+)")


@dataclass
class MailboxAccount:
    host: str
    port: int
    username: str
    password: str = field(repr=False)   # never printed

    def __post_init__(self):
        if _FORBIDDEN_CHARS.search(self.username or "") or _FORBIDDEN_CHARS.search(self.password or ""):
            # CR/LF/NUL could inject IMAP commands.
            raise ValueError("control characters are not allowed in credentials")


@dataclass
class FetchRecord:
    seq: int
    meta: bytes
    literal: bytes | None
    uid: int | None = None
    size: int | None = None
    internal_date: datetime | None = None
    thread_id: str | None = None


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------
class PinnedIMAP4_SSL(imaplib.IMAP4_SSL):
    """IMAP over TLS to a pre-validated IP, verifying the certificate for `host`."""

    def __init__(self, host: str, pinned_ip: str, port: int, *, ssl_context: ssl.SSLContext, timeout: float):
        self._pinned_ip = pinned_ip          # must be set before super().__init__ opens the socket
        super().__init__(host, port, ssl_context=ssl_context, timeout=timeout)

    def _create_socket(self, timeout):
        sock = socket.create_connection((self._pinned_ip, self.port), timeout)
        try:
            return self.ssl_context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def build_tls_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()          # CERT_REQUIRED + check_hostname=True
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def _default_connect(host: str, pinned_ip: str, port: int, timeout: float) -> imaplib.IMAP4:
    return PinnedIMAP4_SSL(host, pinned_ip, port, ssl_context=build_tls_context(), timeout=timeout)


# Indirection points (tests swap these for an in-memory fake; production never does).
connect_imap = _default_connect
resolve_address = resolve_public_address


def _translate_transport_error(exc: BaseException) -> EmailProviderError:
    if isinstance(exc, EmailProviderError):
        return exc
    if isinstance(exc, ssl.SSLCertVerificationError):
        return TLSVerificationFailed()
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return ProviderTimeout()
    if isinstance(exc, ssl.SSLError):
        return TLSVerificationFailed()
    return ProviderUnavailable()


def open_session(account: MailboxAccount, timeout: float) -> "MailboxSession":
    """Resolve (SSRF-checked), connect with verified TLS, and log in."""
    pinned_ip = resolve_address(account.host, account.port)
    try:
        conn = connect_imap(account.host, pinned_ip, account.port, timeout)
    except (imaplib.IMAP4.error, OSError, ssl.SSLError) as exc:
        raise _translate_transport_error(exc) from None

    try:
        conn.login(account.username, account.password)
    except imaplib.IMAP4.abort:
        _quiet_logout(conn)
        raise ProviderUnavailable() from None
    except imaplib.IMAP4.error:
        # Server answered NO/BAD to LOGIN → credentials rejected.
        _quiet_logout(conn)
        raise AuthenticationFailed() from None
    except (OSError, ssl.SSLError) as exc:
        _quiet_logout(conn)
        raise _translate_transport_error(exc) from None

    return MailboxSession(conn)


def _quiet_logout(conn) -> None:
    try:
        conn.logout()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------
class MailboxSession:
    """A logged-in IMAP connection. Not thread-safe; use sequentially."""

    def __init__(self, conn):
        self._conn = conn
        self._selected = False
        caps = getattr(conn, "capabilities", ()) or ()
        self.capabilities = {c.decode() if isinstance(c, bytes) else str(c) for c in caps}

    @property
    def supports_gmail_extensions(self) -> bool:
        return "X-GM-EXT-1" in self.capabilities

    def _run(self, fn, *args):
        try:
            typ, data = fn(*args)
        except imaplib.IMAP4.abort:
            raise ProviderUnavailable() from None
        except imaplib.IMAP4.error:
            raise MailboxError() from None
        except (OSError, ssl.SSLError) as exc:
            raise _translate_transport_error(exc) from None
        if typ != "OK":
            raise MailboxError()
        return data

    def select_readonly(self, mailbox: str = "INBOX") -> int | None:
        """EXAMINE the mailbox (read-only). Returns UIDVALIDITY if reported."""
        self._run(self._conn.select, _quote_mailbox(mailbox), True)
        self._selected = True
        try:
            _typ, dat = self._conn.response("UIDVALIDITY")
            if dat and dat[0]:
                return int(dat[0])
        except Exception:
            pass
        return None

    def search_uids_since(self, since: date) -> list[int]:
        data = self._run(self._conn.uid, "SEARCH", "SINCE", imap_date(since))
        raw = data[0] if data else b""
        if not raw:
            return []
        uids = []
        for token in raw.split():
            if token.isdigit():
                uids.append(int(token))
        return sorted(set(uids))

    def fetch_headers(self, uids: list[int]) -> list[FetchRecord]:
        if not uids:
            return []
        items = [
            "UID", "INTERNALDATE", "RFC822.SIZE",
            "BODY.PEEK[HEADER.FIELDS (MESSAGE-ID FROM TO SUBJECT DATE LIST-ID LIST-UNSUBSCRIBE)]",
        ]
        if self.supports_gmail_extensions:
            items.append("X-GM-THRID")
        uid_set = ",".join(str(u) for u in uids)
        data = self._run(self._conn.uid, "FETCH", uid_set, "(" + " ".join(items) + ")")
        return [r for r in parse_fetch_response(data) if r.uid is not None]

    def fetch_body(self, uid: int, max_bytes: int) -> bytes:
        data = self._run(self._conn.uid, "FETCH", str(int(uid)), f"(UID BODY.PEEK[]<0.{int(max_bytes)}>)")
        for rec in parse_fetch_response(data):
            if rec.uid == uid or rec.uid is None:
                return rec.literal or b""
        return b""

    def close(self) -> None:
        if self._selected:
            try:
                self._conn.close()
            except Exception:
                pass
        _quiet_logout(self._conn)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def imap_date(d: date) -> str:
    """RFC 3501 date (locale-independent)."""
    return f"{d.day:02d}-{_MONTHS[d.month - 1]}-{d.year:04d}"


def since_date(days_back: int, now: datetime | None = None) -> date:
    now = now or datetime.now(timezone.utc)
    return (now - timedelta(days=int(days_back))).date()


def _quote_mailbox(name: str) -> str:
    name = (name or "INBOX").replace("\\", "\\\\").replace('"', '\\"')
    if _FORBIDDEN_CHARS.search(name):
        raise MailboxError()
    return f'"{name}"'


def parse_internaldate(value: bytes | str | None) -> datetime | None:
    """Parse '17-Jul-1996 02:44:25 -0700' → aware UTC datetime."""
    if not value:
        return None
    s = value.decode("ascii", "replace") if isinstance(value, bytes) else value
    m = re.match(r"\s*(\d{1,2})-([A-Za-z]{3})-(\d{4}) (\d{2}):(\d{2}):(\d{2}) ([+-])(\d{2})(\d{2})", s)
    if not m:
        return None
    day, mon, year, hh, mm, ss, sign, oh, om = m.groups()
    month = _MONTH_INDEX.get(mon.lower())
    if not month:
        return None
    try:
        offset = timedelta(hours=int(oh), minutes=int(om))
        tz = timezone(offset if sign == "+" else -offset)
        return datetime(int(year), month, int(day), int(hh), int(mm), int(ss), tzinfo=tz).astimezone(timezone.utc)
    except ValueError:
        return None


def parse_fetch_response(data) -> list[FetchRecord]:
    """Group imaplib FETCH output into one record per message.

    imaplib returns a list mixing (prefix, literal) tuples and plain bytes
    (continuations such as b' UID 5)' or b')'). Data items may appear before or
    after the literal, and some servers send an empty section as "" (no literal).
    """
    records: list[FetchRecord] = []
    current: FetchRecord | None = None
    for item in data or []:
        if item is None:
            continue
        if isinstance(item, tuple):
            head = item[0] if item and isinstance(item[0], bytes) else b""
            lit = item[1] if len(item) > 1 and isinstance(item[1], bytes) else None
            m = _FETCH_START.match(head)
            if m:
                current = FetchRecord(seq=int(m.group(1)), meta=head, literal=lit)
                records.append(current)
            elif current is not None:
                current.meta += b" " + head
                if current.literal is None:
                    current.literal = lit
        elif isinstance(item, bytes):
            m = _FETCH_START.match(item)
            if m:
                current = FetchRecord(seq=int(m.group(1)), meta=item, literal=None)
                records.append(current)
            elif current is not None:
                current.meta += b" " + item

    for rec in records:
        if (m := _UID_RE.search(rec.meta)):
            rec.uid = int(m.group(1))
        if (m := _SIZE_RE.search(rec.meta)):
            rec.size = int(m.group(1))
        if (m := _INTERNALDATE_RE.search(rec.meta)):
            rec.internal_date = parse_internaldate(m.group(1))
        if (m := _THRID_RE.search(rec.meta)):
            rec.thread_id = m.group(1).decode()
    return records
