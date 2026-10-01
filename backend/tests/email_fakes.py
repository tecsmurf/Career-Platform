"""
Test doubles for the email integration.

FakeImapServer / FakeIMAP mimic imaplib.IMAP4's API and — importantly — its
*response shapes* (lists mixing (prefix, literal) tuples and bytes), so tests
exercise the real parser, session, provider and sync code. They plug in at the
two indirection points in imap_client: `resolve_address` and `connect_imap`.
"""
import imaplib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
PUBLIC_TEST_IP = "93.184.216.34"


def internaldate(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    return f"{dt.day:02d}-{_MONTHS[dt.month - 1]}-{dt.year} {dt:%H:%M:%S} +0000"


def make_email(
    frm: str,
    subject: str,
    body: str,
    *,
    msgid: str | None = "auto",
    html: bool = False,
    charset: str = "utf-8",
    extra_headers: str = "",
    to: str = "me@example.com",
) -> bytes:
    if msgid == "auto":
        msgid = f"<{abs(hash((frm, subject, body)))}@mail.test>"
    lines = [f"From: {frm}", f"To: {to}", f"Subject: {subject}", "Date: Mon, 21 Sep 2026 10:00:00 +0000"]
    if msgid:
        lines.append(f"Message-ID: {msgid}")
    if extra_headers:
        lines.append(extra_headers.rstrip("\r\n"))
    lines += ["MIME-Version: 1.0", f"Content-Type: {'text/html' if html else 'text/plain'}; charset={charset}", ""]
    return ("\r\n".join(lines) + "\r\n" + body).encode(charset, errors="replace")


@dataclass
class FakeMessage:
    uid: int
    raw: bytes
    received: datetime


@dataclass
class FakeMailbox:
    username: str
    password: str
    messages: list[FakeMessage] = field(default_factory=list)
    next_uid: int = 100
    uidvalidity: int = 42
    fail_body_uids: set = field(default_factory=set)      # UID FETCH body → NO
    abort_on_body_fetch: int | None = None                  # Nth body fetch drops the connection

    def add(self, raw: bytes, days_ago: float = 1) -> int:
        self.next_uid += 1
        self.messages.append(
            FakeMessage(self.next_uid, raw, datetime.now(timezone.utc) - timedelta(days=days_ago))
        )
        return self.next_uid


class FakeImapServer:
    """Holds mailboxes and records everything the client did."""

    def __init__(self):
        self.mailboxes: dict[str, FakeMailbox] = {}
        self.connect_error: BaseException | None = None
        self.connections: list[dict] = []
        self.commands: list[tuple] = []
        self.body_fetch_sizes: list[int] = []
        self.logins: list[str] = []
        self.logouts = 0
        self.uid_after_literal = False      # vary imaplib response layout

    def add_mailbox(self, username: str, password: str) -> FakeMailbox:
        mb = FakeMailbox(username=username, password=password)
        self.mailboxes[username] = mb
        return mb

    # Plugs into imap_client.connect_imap
    def connect(self, host, pinned_ip, port, timeout):
        self.connections.append({"host": host, "ip": pinned_ip, "port": port, "timeout": timeout})
        if self.connect_error is not None:
            raise self.connect_error
        return FakeIMAP(self)

    @property
    def fetches_that_mark_seen(self) -> list:
        """FETCH items that implicitly set \\Seen: RFC822 / BODY[...] without .PEEK."""
        def marks_seen(items: str) -> bool:
            s = items.replace("RFC822.SIZE", "").replace("BODY.PEEK[", "")
            return "RFC822" in s or "BODY[" in s
        return [c for c in self.commands if c[0] == "FETCH" and marks_seen(c[2])]

    @property
    def readwrite_selects(self) -> list:
        return [c for c in self.commands if c[0] == "SELECT" and not c[2]]


class FakeIMAP:
    def __init__(self, server: FakeImapServer):
        self.server = server
        self.mb: FakeMailbox | None = None
        self.capabilities = ("IMAP4REV1", "IDLE", "UIDPLUS")
        self.body_fetches = 0

    def login(self, user, password):
        mb = self.server.mailboxes.get(user)
        if mb is None or mb.password != password:
            raise imaplib.IMAP4.error("b'[AUTHENTICATIONFAILED] Invalid credentials (Failure)'")
        self.mb = mb
        self.server.logins.append(user)
        return "OK", [b"LOGIN completed"]

    def select(self, mailbox="INBOX", readonly=False):
        self.server.commands.append(("SELECT", mailbox, readonly))
        return "OK", [str(len(self.mb.messages)).encode()]

    def response(self, code):
        if code == "UIDVALIDITY":
            return code, [str(self.mb.uidvalidity).encode()]
        return code, [None]

    def uid(self, command, *args):
        command = command.upper()
        if command == "SEARCH":
            self.server.commands.append(("SEARCH",) + args)
            since = datetime.strptime(args[1], "%d-%b-%Y").date()
            uids = [m.uid for m in self.mb.messages if m.received.date() >= since]
            return "OK", [" ".join(str(u) for u in uids).encode()]
        if command == "FETCH":
            uid_set, items = args
            self.server.commands.append(("FETCH", uid_set, items))
            wanted = {int(u) for u in uid_set.split(",")}
            msgs = [(i + 1, m) for i, m in enumerate(self.mb.messages) if m.uid in wanted]
            if "HEADER.FIELDS" in items:
                return "OK", self._fetch_headers(msgs, items)
            m = re.search(r"BODY\.PEEK\[\]<0\.(\d+)>", items)
            if m:
                self.body_fetches += 1
                if self.mb.abort_on_body_fetch and self.body_fetches >= self.mb.abort_on_body_fetch:
                    raise imaplib.IMAP4.abort("socket error: EOF")
                limit = int(m.group(1))
                self.server.body_fetch_sizes.append(limit)
                (seq, msg), = msgs
                if msg.uid in self.mb.fail_body_uids:
                    return "NO", [b"Message unavailable"]
                data = msg.raw[:limit]
                return "OK", [(f"{seq} (UID {msg.uid} BODY[]<0> {{{len(data)}}}".encode(), data), b")"]
            return "OK", []
        raise imaplib.IMAP4.error("unsupported")

    def _fetch_headers(self, msgs, items):
        fields = re.search(r"HEADER\.FIELDS \(([^)]*)\)", items).group(1).lower().split()
        out = []
        for seq, msg in msgs:
            head = msg.raw.split(b"\r\n\r\n", 1)[0].decode("latin-1").split("\r\n")
            kept = [line for line in head if line.split(":", 1)[0].strip().lower() in fields]
            block = ("\r\n".join(kept) + "\r\n\r\n").encode("latin-1")
            meta = f'UID {msg.uid} INTERNALDATE "{internaldate(msg.received)}" RFC822.SIZE {len(msg.raw)}'
            section = f"BODY[HEADER.FIELDS ({' '.join(f.upper() for f in fields)})]"
            if self.server.uid_after_literal:
                out.append((f"{seq} (INTERNALDATE \"{internaldate(msg.received)}\" {section} {{{len(block)}}}".encode(), block))
                out.append(f" UID {msg.uid} RFC822.SIZE {len(msg.raw)})".encode())
            else:
                out.append((f"{seq} ({meta} {section} {{{len(block)}}}".encode(), block))
                out.append(b")")
        return out

    def close(self):
        return "OK", [b"CLOSE completed"]

    def logout(self):
        self.server.logouts += 1
        return "BYE", [b"LOGOUT"]


# ---------------------------------------------------------------------------
# Fake OpenAI client
# ---------------------------------------------------------------------------
class FakeCompletions:
    def __init__(self, content=None, exc=None):
        self.content, self.exc, self.calls = content, exc, []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc:
            raise self.exc
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))])


class FakeOpenAI:
    def __init__(self, content=None, exc=None):
        self.completions = FakeCompletions(content, exc)
        self.chat = SimpleNamespace(completions=self.completions)


# ---------------------------------------------------------------------------
# Realistic sample emails
# ---------------------------------------------------------------------------
STRIPE_CONFIRM = make_email(
    "Stripe <no-reply@us.greenhouse-mail.io>", "Thank you for applying to Stripe",
    "Hi Aditya,\n\nThanks for applying to the Backend Engineer position at Stripe. "
    "We will review your application and get back to you.\n"
    "View the posting: https://boards.greenhouse.io/stripe/jobs/12345",
    msgid="<confirm-stripe@greenhouse.test>",
)
STRIPE_INTERVIEW = make_email(
    "Maya Chen <maya@stripe.com>", "Interview invitation - Backend Engineer",
    "Hi Aditya, we'd like to schedule a technical interview for the Backend Engineer role at Stripe. "
    "Please share your availability.",
    msgid="<interview-stripe@stripe.test>",
)
NOTION_INTERVIEW = make_email(
    "Priya Shah <priya@notion.so>", "Interview invitation - Full-Stack Engineer",
    "Hi Aditya, we'd like to schedule a technical interview for the Full-Stack Engineer role at Notion. "
    "Please share your availability: https://calendly.com/priya/30min",
    msgid="<interview-notion@notion.test>",
)
LINEAR_REJECTION = make_email(
    "Linear Recruiting <careers@linear.app>", "Your application to Linear",
    "Thank you for applying to Linear. Unfortunately, we have decided to move forward with other "
    "candidates for the Product Engineer role.",
    msgid="<reject-linear@linear.test>",
)
RAMP_OFFER = make_email(
    "Ramp Talent <talent@ramp.com>", "Offer letter - AI Engineer",
    "Congratulations! Following your final interview, we are pleased to extend an offer for the "
    "AI Engineer position at Ramp. Base salary $180,000 - $210,000.",
    msgid="<offer-ramp@ramp.test>",
)
AMAZON_ORDER = make_email(
    "Amazon <order-update@amazon.in>", "Your order has shipped", "Your package will arrive Tuesday.",
    msgid="<order-1@amazon.test>",
)
LINKEDIN_ALERT = make_email(
    "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>", "30 new jobs for 'backend engineer'",
    "Jobs you may be interested in. Apply now.", msgid="<alert-1@linkedin.test>",
)
