"""
Account email: verification codes, password reset, Brevo client.

No real email is sent: the mailer dependency is replaced by FakeMailer, and
the Brevo client itself is tested against httpx.MockTransport.
"""
import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, update

from app.core.config import Settings, settings
from app.core.rate_limit import SlidingWindowLimiter
from app.main import app
from app.models import EmailCode, User, UserAuthState
from app.services import auth_service, email_auth
from app.services.mailer import BrevoMailer, MailerError, build_code_email, get_mailer
from tests.conftest import test_session as db_session_factory

PASSWORD = "secret123"
CODE_RE = re.compile(r"Your code: (\d{6})")


class FakeMailer:
    def __init__(self):
        self.sent = []
        self.fail = False

    async def send(self, message):
        if self.fail:
            raise MailerError("The email service did not accept the message.")
        self.sent.append(message)
        return f"<msg-{len(self.sent)}@test>"

    def last_code(self, to: str | None = None) -> str:
        msgs = [m for m in self.sent if to is None or m.to_email == to]
        return CODE_RE.search(msgs[-1].text).group(1)


@pytest.fixture
def mail(monkeypatch):
    fake = FakeMailer()
    monkeypatch.setattr(settings, "BREVO_API_KEY", "test-brevo-key-not-real")
    monkeypatch.setattr(settings, "MAIL_FROM_ADDRESS", "no-reply@careers.example.com")
    app.dependency_overrides[get_mailer] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_mailer, None)


async def register(client, email="ada@example.com", password=PASSWORD, name="Ada Lovelace"):
    return await client.post("/api/auth/register", json={"email": email, "password": password, "full_name": name})


async def signup(client, email="ada@example.com", password=PASSWORD, name="Ada Lovelace") -> str:
    """Register with account email on; returns the verification ticket."""
    res = await register(client, email=email, password=password, name=name)
    assert res.status_code == 201, res.text
    return res.json()["verification_ticket"]


async def login(client, email="ada@example.com", password=PASSWORD):
    return await client.post("/api/auth/login", data={"username": email, "password": password})


async def verify(client, ticket, code):
    return await client.post("/api/auth/verify-email", json={"ticket": ticket, "code": code})


async def resend(client, ticket):
    return await client.post("/api/auth/resend-verification", json={"ticket": ticket})


async def forgot(client, email="ada@example.com", ticket=None):
    body = {"email": email} if ticket is None else {"email": email, "ticket": ticket}
    return await client.post("/api/auth/forgot-password", json=body)


async def reset_ticket(client, email="ada@example.com") -> str:
    res = await forgot(client, email=email)
    assert res.status_code == 200, res.text
    return res.json()["reset_ticket"]


async def reset(client, ticket, code, new_password="brand-new-1"):
    return await client.post("/api/auth/reset-password",
                             json={"ticket": ticket, "code": code, "new_password": new_password})


async def age_codes(email: str, seconds: int):
    """Move every code of the account back in time (as if `seconds` had passed)."""
    async with db_session_factory() as s:
        user = (await s.execute(select(User).where(User.email == email))).scalar_one()
        rows = (await s.execute(select(EmailCode).where(EmailCode.user_id == user.id))).scalars().all()
        for row in rows:
            row.created_at = _aware(row.created_at) - timedelta(seconds=seconds)
        await s.commit()


def _aware(value):
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def wrong(code: str) -> str:
    return f"{(int(code) + 1) % 1_000_000:06d}"


# ---------------------------------------------------------------------------
# Off by default
# ---------------------------------------------------------------------------
async def test_config_reports_features_off_without_brevo(client):
    res = await client.get("/api/auth/config")
    assert res.status_code == 200
    assert res.json()["email_verification"] is False and res.json()["password_reset"] is False


async def test_without_brevo_register_returns_token_and_code_endpoints_are_unavailable(client):
    res = await register(client)
    assert res.status_code == 201 and res.json()["access_token"]
    assert "verification_ticket" not in res.json()
    for path, body in (
        ("/api/auth/forgot-password", {"email": "ada@example.com"}),
        ("/api/auth/resend-verification", {"ticket": "x" * 20}),
        ("/api/auth/verify-email", {"ticket": "x" * 20, "code": "123456"}),
        ("/api/auth/reset-password", {"ticket": "x" * 20, "code": "123456", "new_password": "newpass99"}),
    ):
        r = await client.post(path, json=body)
        assert r.status_code == 503, path
        assert r.json()["detail"]["code"] == "email_auth_unavailable"


def test_settings_validation():
    with pytest.raises(ValidationError, match="MAIL_FROM_ADDRESS is required"):
        Settings(BREVO_API_KEY="xkeysib-abc", MAIL_FROM_ADDRESS="")
    with pytest.raises(ValidationError, match="plain email address"):
        Settings(BREVO_API_KEY="xkeysib-abc", MAIL_FROM_ADDRESS="Careers <no-reply@x.com>")
    with pytest.raises(ValidationError, match="MAIL_DAILY_SIGNUP_LIMIT"):
        Settings(MAIL_DAILY_SEND_LIMIT=10, MAIL_DAILY_SIGNUP_LIMIT=20)
    ok = Settings(BREVO_API_KEY="xkeysib-abc", MAIL_FROM_ADDRESS="no-reply@x.com")
    assert ok.email_auth_active
    assert not Settings(BREVO_API_KEY="xkeysib-abc", MAIL_FROM_ADDRESS="no-reply@x.com",
                        EMAIL_AUTH_ENABLED=False).email_auth_active


# ---------------------------------------------------------------------------
# Sign-up verification
# ---------------------------------------------------------------------------
async def test_register_sends_code_and_withholds_token_until_verified(client, mail):
    assert (await client.get("/api/auth/config")).json()["email_verification"] is True

    res = await register(client, email="  Ada@Example.COM ")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["verification_required"] is True and body["email"] == "ada@example.com"
    assert "access_token" not in body and body["verification_ticket"]
    ticket = body["verification_ticket"]
    assert len(mail.sent) == 1
    message = mail.sent[0]
    assert message.to_email == "ada@example.com"
    code = mail.last_code()
    assert code in message.subject and code in message.html

    # The ticket is not a session.
    client.headers["Authorization"] = f"Bearer {ticket}"
    assert (await client.get("/api/auth/me")).status_code == 401
    client.headers.pop("Authorization")

    # Password is right but the email is unverified: no session, a fresh
    # ticket, and no second email inside the resend window.
    res = await login(client)
    assert res.status_code == 403
    detail = res.json()["detail"]
    assert detail["code"] == "email_not_verified" and detail["email"] == "ada@example.com"
    assert detail["email_sent"] is True and detail["ticket"]
    assert len(mail.sent) == 1

    assert (await verify(client, detail["ticket"], wrong(code))).status_code == 400
    res = await verify(client, detail["ticket"], code)
    assert res.status_code == 200, res.text
    client.headers["Authorization"] = f"Bearer {res.json()['access_token']}"
    me = (await client.get("/api/auth/me")).json()
    assert me["email"] == "ada@example.com" and me["email_verified"] is True

    # A ticket is never a session, even for a verified account.
    client.headers["Authorization"] = f"Bearer {ticket}"
    assert (await client.get("/api/auth/me")).status_code == 401
    client.headers.pop("Authorization")

    # Codes are single use; normal sign-in works from now on.
    assert (await verify(client, ticket, code)).status_code == 400
    assert (await login(client, email="ADA@EXAMPLE.com")).status_code == 200


async def test_verification_needs_the_ticket(client, mail):
    await signup(client)
    code = mail.last_code()
    assert (await client.post("/api/auth/verify-email", json={"code": code})).status_code == 422
    for bogus in ("not-a-ticket-at-all", auth_service.create_access_token({"sub": "x", "user_id": 1, "tv": 0})):
        res = await verify(client, bogus, code)
        assert res.status_code == 400 and res.json()["detail"]["code"] == "verification_expired"
    expired = email_auth.make_ticket(1, 0)
    claims = auth_service.decode_token(expired)
    from jose import jwt
    claims["exp"] = int((datetime.now(timezone.utc) - timedelta(minutes=1)).timestamp())
    stale = jwt.encode(claims, settings.SECRET_KEY, algorithm="HS256")
    assert (await verify(client, stale, code)).json()["detail"]["code"] == "verification_expired"


async def test_squatter_cannot_get_the_owner_to_verify_their_account(client, mail):
    """Someone registers the victim's address with their own password. The
    victim cannot verify that account (no ticket); they reset the password,
    which verifies the address and locks the squatter out."""
    squatter_ticket = await signup(client, email="victim@example.com", password="squatter-pw")
    assert (await register(client, email="victim@example.com", password="victim-pw")).status_code == 409

    ticket = await reset_ticket(client, email="victim@example.com")
    res = await reset(client, ticket, mail.last_code(), new_password="victim-pw-2")
    assert res.status_code == 200

    assert (await login(client, email="victim@example.com", password="squatter-pw")).status_code == 401
    # The squatter's ticket died with the reset.
    res = await resend(client, squatter_ticket)
    assert res.status_code == 400 and res.json()["detail"]["code"] == "verification_expired"
    assert (await login(client, email="victim@example.com", password="victim-pw-2")).status_code == 200


async def test_only_an_hmac_of_the_code_is_stored(client, mail):
    await signup(client)
    code = mail.last_code()
    async with db_session_factory() as s:
        row = (await s.execute(select(EmailCode))).scalar_one()
        user = (await s.execute(select(User))).scalar_one()
    assert row.code_hash != code and code not in row.code_hash
    assert row.code_hash == email_auth.code_hash("verify_email", user.id, code)
    assert row.sent_to == "ada@example.com" and row.purpose == "verify_email" and row.pool == "signup"
    assert row.sent_at is not None and row.ticket_hash is None


async def test_wrong_guesses_burn_the_code(client, mail, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_CODE_MAX_ATTEMPTS", 3)
    ticket = await signup(client)
    code = mail.last_code()
    for _ in range(3):
        res = await verify(client, ticket, wrong(code))
        assert res.status_code == 400 and res.json()["detail"]["code"] == "invalid_code"
    # Attempts are used up: even the right code is refused now.
    assert (await verify(client, ticket, code)).status_code == 400
    async with db_session_factory() as s:
        assert (await s.execute(select(EmailCode.attempts))).scalar_one() == 3


async def test_parallel_guesses_cannot_exceed_the_attempt_limit(client, mail, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_CODE_MAX_ATTEMPTS", 3)
    ticket = await signup(client)
    code = mail.last_code()
    guesses = [f"{(int(code) + i) % 1_000_000:06d}" for i in range(1, 9)]
    results = await asyncio.gather(*(verify(client, ticket, g) for g in guesses))
    assert all(r.status_code == 400 for r in results)
    async with db_session_factory() as s:
        assert (await s.execute(select(EmailCode.attempts))).scalar_one() == 3


async def test_expired_code_is_refused(client, mail):
    ticket = await signup(client)
    code = mail.last_code()
    async with db_session_factory() as s:
        await s.execute(update(EmailCode).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
        await s.commit()
    assert (await verify(client, ticket, code)).status_code == 400


async def test_resend_respects_cooldown_and_replaces_the_old_code(client, mail):
    ticket = await signup(client)
    first = mail.last_code()

    res = await resend(client, ticket)
    assert res.status_code == 200 and "moments ago" in res.json()["message"]
    assert 1 <= res.json()["resend_after"] <= settings.AUTH_CODE_RESEND_SECONDS + 1
    assert len(mail.sent) == 1  # inside the cooldown: nothing new sent

    await age_codes("ada@example.com", 61)
    res = await resend(client, ticket)
    assert res.status_code == 200 and "new code" in res.json()["message"] and len(mail.sent) == 2
    second = mail.last_code()
    if second != first:
        assert (await verify(client, ticket, first)).status_code == 400
    assert (await verify(client, ticket, second)).status_code == 200
    # Already verified: nothing more is sent.
    res = await resend(client, ticket)
    assert res.status_code == 200 and "already verified" in res.json()["message"] and len(mail.sent) == 2


async def test_hourly_code_cap(client, mail, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_CODE_RESEND_SECONDS", 0)
    monkeypatch.setattr(settings, "AUTH_CODE_MAX_PER_HOUR", 3)
    ticket = await signup(client)  # code 1
    for _ in range(2):              # codes 2 and 3
        assert (await resend(client, ticket)).status_code == 200
    res = await resend(client, ticket)
    assert res.status_code == 429 and res.json()["detail"]["code"] == "too_many_codes"
    assert 1 <= int(res.headers["Retry-After"]) <= 3601
    assert len(mail.sent) == 3
    # The latest code still works.
    assert (await verify(client, ticket, mail.last_code())).status_code == 200


async def test_parallel_requests_cannot_slip_past_the_limits(client, mail):
    await _verified_user(client, mail)
    # Same reset request, in parallel: one email (cooldown).
    ticket = await reset_ticket(client)
    await age_codes("ada@example.com", 61)
    mail.sent.clear()
    results = await asyncio.gather(*(forgot(client, ticket=ticket) for _ in range(8)))
    assert all(r.status_code == 200 for r in results)
    assert len(mail.sent) == 1
    # Fresh requests in parallel: never more than the hourly cap.
    results = await asyncio.gather(*(forgot(client) for _ in range(12)))
    assert len(mail.sent) <= settings.AUTH_CODE_MAX_PER_HOUR
    assert sum(r.status_code == 429 for r in results) >= 12 - settings.AUTH_CODE_MAX_PER_HOUR


async def test_send_failure_on_register_creates_no_account(client, mail):
    mail.fail = True
    res = await register(client)
    assert res.status_code == 503 and res.json()["detail"]["code"] == "email_send_failed"
    async with db_session_factory() as s:
        assert (await s.execute(select(User))).first() is None
        assert (await s.execute(select(EmailCode))).first() is None
        assert (await s.execute(select(UserAuthState))).first() is None
    mail.fail = False
    assert (await register(client)).status_code == 201


async def test_send_failure_on_resend_keeps_the_previous_code(client, mail):
    ticket = await signup(client)
    code = mail.last_code()
    await age_codes("ada@example.com", 61)
    mail.fail = True
    res = await resend(client, ticket)
    assert res.status_code == 503 and res.json()["detail"]["code"] == "email_send_failed"
    mail.fail = False
    async with db_session_factory() as s:
        assert (await s.execute(select(func.count(EmailCode.id)))).scalar_one() == 1
    assert (await verify(client, ticket, code)).status_code == 200


async def test_daily_send_limit_protects_the_provider_quota(client, mail, monkeypatch):
    monkeypatch.setattr(settings, "MAIL_DAILY_SEND_LIMIT", 1)
    monkeypatch.setattr(settings, "MAIL_DAILY_SIGNUP_LIMIT", 1)
    assert (await register(client)).status_code == 201
    res = await register(client, email="grace@example.com", name="Grace")
    assert res.status_code == 503
    assert len(mail.sent) == 1
    async with db_session_factory() as s:
        assert (await s.execute(select(func.count(User.id)))).scalar_one() == 1


async def test_signups_cannot_use_up_the_emails_existing_users_need(client, mail, monkeypatch):
    monkeypatch.setattr(settings, "MAIL_DAILY_SEND_LIMIT", 3)
    monkeypatch.setattr(settings, "MAIL_DAILY_SIGNUP_LIMIT", 1)
    # An account from before account email was switched on.
    monkeypatch.setattr(settings, "BREVO_API_KEY", "")
    assert (await register(client, email="old@example.com")).status_code == 201
    monkeypatch.setattr(settings, "BREVO_API_KEY", "test-brevo-key-not-real")

    assert (await register(client)).status_code == 201                       # uses the sign-up share
    res = await register(client, email="spam1@example.com", name="Spam")
    assert res.status_code == 503 and "sign-ups are paused" in res.json()["detail"]["message"]

    # Codes for the never-verified sign-up come out of the sign-up share too,
    # whatever triggers them …
    res = await forgot(client, email="ada@example.com")
    assert res.status_code == 503 and "sign-ups are paused" in res.json()["detail"]["message"]
    await age_codes("ada@example.com", 61)
    assert (await login(client)).json()["detail"]["email_sent"] is False
    # … so the existing user still gets a verification code and a reset code.
    res = await login(client, email="old@example.com")
    assert res.status_code == 403 and res.json()["detail"]["email_sent"] is True
    assert (await forgot(client, email="old@example.com")).status_code == 200
    assert len(mail.sent) == 3


async def test_login_resends_after_the_cooldown(client, mail):
    await signup(client)
    await age_codes("ada@example.com", 61)
    res = await login(client)
    assert res.status_code == 403 and res.json()["detail"]["email_sent"] is True
    assert len(mail.sent) == 2
    # A wrong password never triggers an email.
    await age_codes("ada@example.com", 61)
    assert (await login(client, password="nope-nope")).status_code == 401
    assert len(mail.sent) == 2


async def test_login_reports_honestly_when_the_code_could_not_be_sent(client, mail):
    await signup(client)
    await age_codes("ada@example.com", 61)
    mail.fail = True
    detail = (await login(client)).json()["detail"]
    assert detail["code"] == "email_not_verified" and detail["email_sent"] is False
    assert "couldn't send" in detail["message"] and detail["ticket"]
    async with db_session_factory() as s:  # the failed code was not kept
        assert (await s.execute(select(func.count(EmailCode.id)))).scalar_one() == 1


async def test_existing_accounts_verify_at_next_sign_in(client, mail, monkeypatch):
    # Account created while account email was off …
    monkeypatch.setattr(settings, "BREVO_API_KEY", "")
    res = await register(client)
    old_token = res.json()["access_token"]
    # … then account email is switched on.
    monkeypatch.setattr(settings, "BREVO_API_KEY", "test-brevo-key-not-real")
    client.headers["Authorization"] = f"Bearer {old_token}"
    assert (await client.get("/api/auth/me")).status_code == 401
    client.headers.pop("Authorization")

    res = await login(client)
    assert res.status_code == 403 and len(mail.sent) == 1
    token = (await verify(client, res.json()["detail"]["ticket"], mail.last_code())).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    assert (await client.get("/api/auth/me")).status_code == 200


async def test_verify_attempts_are_throttled_per_account(client, mail, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_CODE_MAX_ATTEMPTS", 10)
    ticket = await signup(client)
    code = mail.last_code()
    statuses = [(await verify(client, ticket, wrong(code))).status_code for _ in range(11)]
    assert statuses[:10] == [400] * 10 and statuses[-1] == 429


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------
async def _verified_user(client, mail, email="ada@example.com"):
    ticket = await signup(client, email=email)
    token = (await verify(client, ticket, mail.last_code())).json()["access_token"]
    mail.sent.clear()
    return token


async def test_forgot_password_reply_is_the_same_for_unknown_addresses(client, mail):
    await _verified_user(client, mail)
    unknown = await forgot(client, email="nobody@example.com")
    known = await forgot(client, email="Ada@Example.com")
    assert unknown.status_code == known.status_code == 200
    strip = lambda body: {k: v for k, v in body.items() if k != "reset_ticket"}  # noqa: E731
    assert strip(unknown.json()) == strip(known.json())
    assert unknown.json()["reset_ticket"] and known.json()["reset_ticket"]
    assert len(mail.sent) == 1
    assert "reset" in mail.sent[0].subject.lower()


async def test_reset_password_changes_password_and_ends_old_sessions(client, mail):
    old_token = await _verified_user(client, mail)
    ticket = await reset_ticket(client)
    code = mail.last_code()

    assert (await reset(client, ticket, wrong(code))).status_code == 400
    res = await reset(client, ticket, code)
    assert res.status_code == 200, res.text
    new_token = res.json()["access_token"]

    client.headers["Authorization"] = f"Bearer {old_token}"
    assert (await client.get("/api/auth/me")).status_code == 401
    client.headers["Authorization"] = f"Bearer {new_token}"
    assert (await client.get("/api/auth/me")).status_code == 200
    client.headers.pop("Authorization")

    assert (await login(client)).status_code == 401
    assert (await login(client, password="brand-new-1")).status_code == 200
    assert (await reset(client, ticket, code, new_password="another-1")).status_code == 400


async def test_strangers_cannot_burn_or_replace_the_owners_reset_code(client, mail):
    """Reset codes are bound to the ticket they were requested with: a stranger
    who knows only the address gets their own ticket, and neither their wrong
    guesses nor their new requests touch the owner's code."""
    await _verified_user(client, mail)
    owner_ticket = await reset_ticket(client)
    owner_code = mail.last_code()

    for _ in range(3):
        stranger_ticket = await reset_ticket(client)   # each sends a new code (to the owner's inbox)
        statuses = [(await reset(client, stranger_ticket, f"{n:06d}")).status_code for n in range(8)]
        assert set(statuses) == {400}
    assert len(mail.sent) == 4
    # No per-address throttle either: the owner's code still works.
    assert (await reset(client, owner_ticket, owner_code)).status_code == 200


async def test_reset_ticket_is_reused_for_resends_and_bound_to_its_address(client, mail):
    await _verified_user(client, mail)
    await _verified_user(client, mail, email="grace@example.com")
    ticket = await reset_ticket(client)
    first = mail.last_code()
    await age_codes("ada@example.com", 61)
    res = await forgot(client, ticket=ticket)
    assert res.json()["reset_ticket"] == ticket and len(mail.sent) == 2
    second = mail.last_code()
    if second != first:
        assert (await reset(client, ticket, first)).status_code == 400
    # A ticket for one address is never used for another.
    other = (await forgot(client, email="grace@example.com", ticket=ticket)).json()["reset_ticket"]
    assert other != ticket
    # A verification ticket is not a reset ticket.
    vt = email_auth.make_ticket(1, 0)
    res = await reset(client, vt, second)
    assert res.status_code == 400 and res.json()["detail"]["code"] == "reset_expired"
    assert (await reset(client, ticket, second)).status_code == 200


async def test_verify_code_cannot_reset_a_password(client, mail):
    await signup(client)
    verify_code = mail.last_code()
    ticket = await reset_ticket(client)
    if verify_code != mail.last_code():
        assert (await reset(client, ticket, verify_code)).status_code == 400


async def test_reset_also_verifies_an_unverified_account(client, mail):
    await signup(client)
    signup_code = mail.last_code()
    ticket = await reset_ticket(client)
    assert (await reset(client, ticket, mail.last_code())).status_code == 200
    assert (await login(client, password="brand-new-1")).status_code == 200
    async with db_session_factory() as s:  # every outstanding code was invalidated
        live = (await s.execute(select(func.count(EmailCode.id)).where(EmailCode.consumed_at.is_(None)))).scalar_one()
    assert live == 0 and signup_code


async def test_inactive_accounts_get_no_reset_email(client, mail):
    await _verified_user(client, mail)
    async with db_session_factory() as s:
        await s.execute(update(User).values(is_active=False))
        await s.commit()
    res = await forgot(client)
    assert res.status_code == 200 and mail.sent == [] and res.json()["reset_ticket"]


async def test_reset_validates_input_without_echoing_it(client, mail):
    res = await client.post("/api/auth/reset-password",
                            json={"ticket": "t" * 40, "code": "12ab56", "new_password": "x"})
    assert res.status_code == 422
    assert "12ab56" not in res.text


async def test_login_never_pairs_an_old_password_with_a_new_token_version(client, mail, monkeypatch):
    """A reset that commits between reading the user and issuing the token must not
    let the old password produce a session that survives the reset."""
    await _verified_user(client, mail)
    real = auth_service.get_user_by_email

    async def lookup_then_reset(db, email):
        user = await real(db, email)
        async with db_session_factory() as s:  # concurrent reset commits now
            await s.execute(update(User).values(hashed_password=auth_service.hash_password("brand-new-1")))
            await s.execute(update(UserAuthState).values(token_version=UserAuthState.token_version + 1))
            await s.commit()
        return user

    monkeypatch.setattr(auth_service, "get_user_by_email", lookup_then_reset)
    assert (await login(client)).status_code == 401


# ---------------------------------------------------------------------------
# Tokens and email normalisation
# ---------------------------------------------------------------------------
async def test_token_version_mismatch_is_rejected_and_legacy_tokens_work(client):
    res = await register(client)
    token = res.json()["access_token"]
    claims = auth_service.decode_token(token)
    assert claims["tv"] == 0 and "iat" in claims

    legacy = auth_service.create_access_token({"sub": claims["sub"], "user_id": claims["user_id"]})
    client.headers["Authorization"] = f"Bearer {legacy}"
    assert (await client.get("/api/auth/me")).status_code == 200

    async with db_session_factory() as s:
        s.add(UserAuthState(user_id=claims["user_id"], token_version=1))
        await s.commit()
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_emails_are_case_insensitive_and_stored_lowercase(client):
    res = await register(client, email="Mixed.Case@Example.COM")
    assert res.status_code == 201
    async with db_session_factory() as s:
        assert (await s.execute(select(User.email))).scalar_one() == "mixed.case@example.com"
    assert (await register(client, email="MIXED.case@example.com")).status_code == 409
    assert (await login(client, email="MIXED.CASE@example.com")).status_code == 200


async def test_legacy_mixed_case_accounts_still_sign_in(client):
    async with db_session_factory() as s:
        s.add(User(email="Legacy@Example.com", full_name="Legacy", hashed_password=auth_service.hash_password(PASSWORD)))
        await s.commit()
    assert (await login(client, email="Legacy@Example.com")).status_code == 200
    assert (await login(client, email="legacy@example.com")).status_code == 200
    assert (await register(client, email="legacy@example.com")).status_code == 409


async def test_register_rejects_malformed_email(client):
    for bad in ("no-at-sign.com", "a@nodot", "two words@x.com", "@example.com"):
        assert (await register(client, email=bad)).status_code == 422, bad


# ---------------------------------------------------------------------------
# Emails and the Brevo client
# ---------------------------------------------------------------------------
async def test_code_emails_carry_no_user_supplied_text(client, mail):
    await signup(client, name="Your account is locked. Visit evil.example now")
    message = mail.sent[0]
    for part in (message.subject, message.text, message.html):
        assert "evil.example" not in part and "locked" not in part


def _message():
    return build_code_email(purpose="verify_email", code="042917", to_email="ada@example.com", ttl_minutes=15)


async def test_brevo_request_shape():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json={"messageId": "<abc@smtp-relay.mailin.fr>"})

    mailer = BrevoMailer(api_key="xkeysib-secret", sender_email="no-reply@x.com", sender_name="Career Platform",
                         transport=httpx.MockTransport(handler))
    assert await mailer.send(_message()) == "<abc@smtp-relay.mailin.fr>"
    assert seen["url"] == "https://api.brevo.com/v3/smtp/email"
    assert seen["headers"]["api-key"] == "xkeysib-secret"
    body = seen["body"]
    assert body["sender"] == {"email": "no-reply@x.com", "name": "Career Platform"}
    assert body["to"] == [{"email": "ada@example.com"}]
    assert "042917" in body["subject"] and "042917" in body["textContent"] and "042917" in body["htmlContent"]
    assert "15 minutes" in body["textContent"]
    assert "xkeysib-secret" not in repr(mailer)


@pytest.mark.parametrize("status,needle", [(401, "credentials"), (429, "rate-limiting"), (400, "did not accept")])
async def test_brevo_errors_never_leak_the_key(status, needle, caplog):
    def handler(request):
        return httpx.Response(status, json={"code": "unauthorized", "message": "Key xkeysib-secret not found"})

    mailer = BrevoMailer(api_key="xkeysib-secret", sender_email="no-reply@x.com", sender_name="CP",
                         transport=httpx.MockTransport(handler))
    caplog.set_level(logging.DEBUG)
    with pytest.raises(MailerError) as info:
        await mailer.send(_message())
    assert needle in str(info.value)
    assert "xkeysib-secret" not in str(info.value) and "xkeysib-secret" not in caplog.text
    assert "042917" not in caplog.text


async def test_brevo_timeout_and_network_errors():
    def slow(request):
        raise httpx.ReadTimeout("timed out", request=request)

    def down(request):
        raise httpx.ConnectError("refused", request=request)

    for handler, needle in ((slow, "in time"), (down, "could not be reached")):
        mailer = BrevoMailer(api_key="k", sender_email="a@x.com", sender_name="CP", transport=httpx.MockTransport(handler))
        with pytest.raises(MailerError, match=needle):
            await mailer.send(_message())


def test_get_mailer_follows_settings(monkeypatch):
    assert get_mailer() is None
    monkeypatch.setattr(settings, "BREVO_API_KEY", "k")
    monkeypatch.setattr(settings, "MAIL_FROM_ADDRESS", "no-reply@x.com")
    assert isinstance(get_mailer(), BrevoMailer)
    monkeypatch.setattr(settings, "EMAIL_AUTH_ENABLED", False)
    assert get_mailer() is None


async def test_codes_and_keys_stay_out_of_logs(client, mail, caplog):
    caplog.set_level(logging.DEBUG)
    ticket = await signup(client)
    code = mail.last_code()
    await verify(client, ticket, code)
    assert code not in caplog.text
    assert "test-brevo-key-not-real" not in caplog.text and ticket not in caplog.text


# ---------------------------------------------------------------------------
# Limiter memory
# ---------------------------------------------------------------------------
def test_sliding_window_limiter_memory_is_bounded():
    limiter = SlidingWindowLimiter(2, 60, max_keys=100)
    for i in range(5000):
        limiter.hit(f"user{i}@example.com")
    assert len(limiter) <= 100
    # Recently used keys keep their state.
    assert limiter.hit("k") is None and limiter.hit("k") is None and limiter.hit("k") is not None


def test_sliding_window_limiter_sweeps_idle_keys(monkeypatch):
    import app.core.rate_limit as rl

    clock = [1000.0]
    monkeypatch.setattr(rl.time, "monotonic", lambda: clock[0])
    limiter = SlidingWindowLimiter(5, 10)
    for i in range(500):
        limiter.hit(i)
    clock[0] += 11
    for _ in range(SlidingWindowLimiter.SWEEP_EVERY):
        limiter.hit("fresh")
    assert len(limiter) == 1


# ---------------------------------------------------------------------------
# Sending robustness
# ---------------------------------------------------------------------------
class ExplodingMailer(FakeMailer):
    async def send(self, message):
        raise RuntimeError("worker restarted mid-send")


async def test_unexpected_send_errors_leave_no_account_or_code(client, mail):
    app.dependency_overrides[get_mailer] = lambda: ExplodingMailer()
    with pytest.raises(RuntimeError):
        await register(client)
    async with db_session_factory() as s:
        assert (await s.execute(select(func.count(User.id)))).scalar_one() == 0
        assert (await s.execute(select(func.count(EmailCode.id)))).scalar_one() == 0
    app.dependency_overrides[get_mailer] = lambda: mail
    assert (await register(client)).status_code == 201


async def test_a_code_still_being_sent_does_not_hide_the_current_one(client, mail):
    ticket = await signup(client)
    code = mail.last_code()
    async with db_session_factory() as s:
        user = (await s.execute(select(User))).scalar_one()
        s.add(EmailCode(user_id=user.id, purpose="verify_email", pool="signup", code_hash="0" * 64,
                        sent_to=user.email, expires_at=datetime.now(timezone.utc) + timedelta(minutes=15)))
        await s.commit()
    assert (await verify(client, ticket, code)).status_code == 200


async def test_an_abandoned_unsent_code_stops_blocking_new_ones(client, mail):
    ticket = await signup(client)
    await age_codes("ada@example.com", 120)
    async with db_session_factory() as s:
        user = (await s.execute(select(User))).scalar_one()
        stale = datetime.now(timezone.utc) - timedelta(seconds=settings.MAIL_TIMEOUT_SECONDS + 30)
        s.add(EmailCode(user_id=user.id, purpose="verify_email", pool="signup", code_hash="0" * 64,
                        sent_to=user.email, expires_at=stale + timedelta(minutes=15), created_at=stale))
        await s.commit()
    res = await resend(client, ticket)
    assert res.status_code == 200 and "new code" in res.json()["message"]
    assert (await verify(client, ticket, mail.last_code())).status_code == 200


async def test_brevo_odd_success_body_is_tolerated():
    mailer = BrevoMailer(api_key="k", sender_email="a@x.com", sender_name="CP",
                         transport=httpx.MockTransport(lambda r: httpx.Response(201, json=["unexpected"])))
    assert await mailer.send(_message()) == ""


async def test_reset_works_for_a_legacy_mixed_case_account_with_a_lowercase_twin(client, mail):
    async with db_session_factory() as s:
        for email in ("Foo@Example.com", "foo@example.com"):
            s.add(User(email=email, full_name="Foo", hashed_password=auth_service.hash_password(PASSWORD)))
        await s.commit()
    ticket = await reset_ticket(client, email="Foo@Example.com")
    assert mail.sent[-1].to_email == "Foo@Example.com"
    assert (await reset(client, ticket, mail.last_code())).status_code == 200
    assert (await login(client, email="Foo@Example.com", password="brand-new-1")).status_code == 200
    # The twin is untouched: its old password is still accepted (it is just unverified).
    twin = await login(client, email="foo@example.com")
    assert twin.status_code == 403 and twin.json()["detail"]["code"] == "email_not_verified"
