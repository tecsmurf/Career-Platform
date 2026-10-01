"""
Login rate limiter — token bucket tests.

Deterministic: every bucket here reads an injected FakeClock (integer ms), so
"wait 1.2 s" is `clock.advance(1.2)`, not a sleep. The numbered tests map to
the spec's Tests 1–10. Redis-backed tests run against a real redis-server
when one is available (local binary or REDIS_TEST_URL) and skip otherwise.
"""
import asyncio
import logging
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings, settings
from app.core.token_bucket import (
    BucketPolicy,
    FailoverTokenBuckets,
    MemoryTokenBuckets,
    RedisTokenBuckets,
    take_token,
)
from app.main import app
from app.services import auth_service
from app.services.login_limiter import RATE_LIMITED_DETAIL, login_limiter

ACCOUNT = BucketPolicy.from_seconds(50, 1.2)
PASSWORD = "testpass123"


class FakeClock:
    def __init__(self, start_ms: int = 5_000_000):
        self.now = start_ms

    def __call__(self) -> int:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += round(seconds * 1000)


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def store(clock):
    s = MemoryTokenBuckets(clock=clock)
    login_limiter.use_store(s)
    return s


def drain(store, key, policy=ACCOUNT, n=None):
    n = policy.capacity if n is None else n
    return [store.take_sync(key, policy).allowed for _ in range(n)]


@pytest_asyncio.fixture
async def make_ip_client():
    clients = []

    def _make(ip: str) -> AsyncClient:
        ac = AsyncClient(transport=ASGITransport(app=app, client=(ip, 41000)), base_url="http://test")
        clients.append(ac)
        return ac

    yield _make
    for ac in clients:
        await ac.aclose()


async def register(client, email, password=PASSWORD):
    res = await client.post("/api/auth/register", json={"email": email, "password": password, "full_name": "U"})
    assert res.status_code == 201, res.text


async def login(client, email, password=PASSWORD, **kw):
    return await client.post("/api/auth/login", data={"username": email, "password": password}, **kw)


# ---------------------------------------------------------------------------
# The algorithm (store level) — Tests 1–7
# ---------------------------------------------------------------------------
class TestTokenBucketAlgorithm:
    def test_1_fresh_bucket_allows_50_attempts(self, store):
        assert drain(store, "a") == [True] * 50

    def test_2_51st_immediate_attempt_is_rejected(self, store):
        drain(store, "a")
        d = store.take_sync("a", ACCOUNT)
        assert not d.allowed and d.retry_after_ms == 1200

    def test_3_one_token_after_1_2_seconds(self, store, clock):
        drain(store, "a")
        clock.advance(1.199)
        assert not store.take_sync("a", ACCOUNT).allowed      # not a millisecond early
        clock.advance(0.001)
        assert store.take_sync("a", ACCOUNT).allowed          # exactly one token…
        assert not store.take_sync("a", ACCOUNT).allowed      # …not two

    def test_4_another_token_after_another_1_2_seconds(self, store, clock):
        drain(store, "a")
        clock.advance(1.2)
        assert store.take_sync("a", ACCOUNT).allowed
        clock.advance(1.2)
        assert store.take_sync("a", ACCOUNT).allowed
        assert not store.take_sync("a", ACCOUNT).allowed

    def test_partial_refill_is_gradual_not_a_window_reset(self, store, clock):
        drain(store, "a")
        clock.advance(10 * 1.2 + 0.5)
        assert drain(store, "a", n=11) == [True] * 10 + [False]
        # The 0.5 s remainder carries over: the next token is 0.7 s away, not 1.2 s.
        assert store.take_sync("a", ACCOUNT).retry_after_ms == 700
        clock.advance(60)                     # long enough to refill completely:
        assert drain(store, "a", n=51) == [True] * 50 + [False]   # back to 50, never more

    def test_5_tokens_never_exceed_capacity(self, store, clock):
        drain(store, "a", n=10)
        for _ in range(5):
            clock.advance(3600)
            store.take_sync("a", ACCOUNT)
            assert store.peek("a") == 49   # refilled to 50 (capped), minus this attempt
        drain(store, "a", n=49)
        assert not store.take_sync("a", ACCOUNT).allowed

    def test_full_bucket_banks_no_partial_credit(self, store, clock):
        store.take_sync("a", ACCOUNT)          # 49 left, refill clock starts now
        clock.advance(1.2)                     # back to 50 (full)
        clock.advance(1.1)                     # time spent full must not count…
        drain(store, "a", n=49)
        store.take_sync("a", ACCOUNT)          # now empty
        assert store.take_sync("a", ACCOUNT).retry_after_ms == 1200   # …so a full 1.2 s wait

    def test_clock_going_backwards_never_mints_tokens(self):
        tokens, last, d = take_token(0, 10_000, 4_000, ACCOUNT)
        assert not d.allowed and tokens == 0 and last == 4_000
        tokens, last, d = take_token(tokens, last, 5_199, ACCOUNT)
        assert not d.allowed

    def test_6_concurrent_requests_cannot_both_take_the_last_token(self, store):
        drain(store, "a", n=49)               # exactly one token left
        barrier = threading.Barrier(16)
        results = []

        def worker():
            barrier.wait()
            results.append(store.take_sync("a", ACCOUNT).allowed)

        threads = [threading.Thread(target=worker) for _ in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert results.count(True) == 1 and results.count(False) == 15

    def test_7_accounts_have_independent_buckets(self, store):
        drain(store, "user-a")
        assert not store.take_sync("user-a", ACCOUNT).allowed
        assert drain(store, "user-b") == [True] * 50

    def test_memory_is_bounded(self, clock):
        s = MemoryTokenBuckets(clock=clock, max_keys=100, prune_every_ms=1_000)
        for i in range(250):
            s.take_sync(f"k{i}", ACCOUNT)
        assert len(s) <= 100                            # LRU cap holds under a key flood
        clock.advance(61)                               # every bucket is full again → prunable
        s.take_sync("fresh", ACCOUNT)
        assert len(s) == 1


# ---------------------------------------------------------------------------
# The login endpoint — Tests 2, 6, 8, 9, 10 end to end
# ---------------------------------------------------------------------------
class TestLoginEndpoint:
    async def test_51st_attempt_gets_429_with_retry_after(self, client, store):
        await register(client, "victim@example.com")
        for _ in range(50):
            assert (await login(client, "victim@example.com", "wrong-password")).status_code == 401
        res = await login(client, "victim@example.com", "wrong-password")
        assert res.status_code == 429
        assert res.json() == {"detail": RATE_LIMITED_DETAIL}
        assert res.headers["Retry-After"] == "2"            # 1.2 s, rounded up to whole seconds

    async def test_429_reveals_nothing_about_account_existence(self, client, store, monkeypatch):
        monkeypatch.setattr(settings, "LOGIN_IP_LIMIT", "off")   # isolate the account bucket
        await register(client, "real@example.com")
        for email in ("real@example.com", "nobody@example.com"):
            for _ in range(50):
                assert (await login(client, email, "wrong-password")).status_code == 401
        real = await login(client, "real@example.com", "wrong-password")
        ghost = await login(client, "nobody@example.com", "wrong-password")
        assert real.status_code == ghost.status_code == 429
        assert real.json() == ghost.json() == {"detail": RATE_LIMITED_DETAIL}
        assert real.headers["Retry-After"] == ghost.headers["Retry-After"]
        body = real.text.lower()
        assert "token" not in body and "50" not in body and "redis" not in body

    async def test_bad_credentials_keep_the_generic_message(self, client, store):
        await register(client, "user@example.com")
        wrong = await login(client, "user@example.com", "nope-nope")
        unknown = await login(client, "ghost@example.com", "nope-nope")
        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json() == unknown.json() == {"detail": "Incorrect email or password"}

    async def test_limit_is_enforced_before_password_verification(self, client, store, monkeypatch):
        await register(client, "user@example.com")
        drain(store, "acct:" + _acct_digest("user@example.com"))
        calls = []
        real_verify = auth_service.verify_password
        monkeypatch.setattr(auth_service, "verify_password", lambda p, h: calls.append(1) or real_verify(p, h))
        res = await login(client, "user@example.com")          # correct password, empty bucket
        assert res.status_code == 429 and calls == []           # bcrypt never ran

    async def test_unknown_accounts_cost_the_same_bcrypt_work(self, client, store, monkeypatch):
        calls = []
        real_verify = auth_service.verify_password
        monkeypatch.setattr(auth_service, "verify_password", lambda p, h: calls.append(1) or real_verify(p, h))
        assert (await login(client, "ghost@example.com", "whatever1")).status_code == 401
        assert calls == [1]

    async def test_identifier_is_normalised(self, client, store):
        await register(client, "user@example.com")
        for i in range(50):
            variant = ["user@example.com", "  USER@example.com ", "User@Example.COM"][i % 3]
            await login(client, variant, "wrong-password")
        assert (await login(client, "user@EXAMPLE.com", "wrong-password")).status_code == 429

    async def test_6_concurrent_logins_cannot_share_the_last_token(self, client, store):
        await register(client, "user@example.com")
        drain(store, "acct:" + _acct_digest("user@example.com"), n=49)
        results = await asyncio.gather(*(login(client, "user@example.com", "wrong-password") for _ in range(6)))
        codes = sorted(r.status_code for r in results)
        assert codes == [401, 429, 429, 429, 429, 429]

    async def test_8_different_ips_share_the_account_bucket(self, make_ip_client, store):
        a, b = make_ip_client("203.0.113.10"), make_ip_client("198.51.100.20")
        await register(a, "user@example.com")
        for _ in range(50):
            assert (await login(a, "user@example.com", "wrong-password")).status_code == 401
        res = await login(b, "user@example.com", "wrong-password")
        assert res.status_code == 429                 # moving IP does not reset the account bucket
        assert (await login(b, "other@example.com", "wrong-password")).status_code == 401

    async def test_9_same_ip_different_accounts_are_independent(self, make_ip_client, store):
        c = make_ip_client("203.0.113.10")
        await register(c, "a@example.com")
        await register(c, "b@example.com")
        for _ in range(50):
            await login(c, "a@example.com", "wrong-password")
        assert (await login(c, "a@example.com", "wrong-password")).status_code == 429
        assert (await login(c, "b@example.com")).status_code == 200   # b's bucket is untouched

    async def test_10_successful_logins_consume_tokens_but_never_lock_out(self, client, store, clock):
        """Policy: every attempt that reaches verification costs a token, success
        included — the bucket bounds password checks. It refills continuously, so
        a legitimate user is never locked out: at worst they wait ~1.2 s."""
        await register(client, "busy@example.com")
        for _ in range(50):
            assert (await login(client, "busy@example.com")).status_code == 200
        res = await login(client, "busy@example.com")
        assert res.status_code == 429 and res.headers["Retry-After"] == "2"
        clock.advance(1.2)
        res = await login(client, "busy@example.com")
        assert res.status_code == 200 and res.json()["access_token"]

    async def test_retry_after_is_readable_cross_origin(self, client, store):
        drain(store, "acct:" + _acct_digest("user@example.com"))
        res = await login(client, "user@example.com", "wrong-password", headers={"Origin": "http://localhost:5173"})
        assert res.status_code == 429
        assert res.headers["access-control-allow-origin"] == "http://localhost:5173"
        assert "retry-after" in res.headers["access-control-expose-headers"].lower()

    async def test_disabled_flag_turns_limiter_off(self, client, store, monkeypatch):
        monkeypatch.setattr(settings, "LOGIN_RATE_LIMIT_ENABLED", False)
        for _ in range(55):
            assert (await login(client, "ghost@example.com", "wrong-password")).status_code == 401


def _acct_digest(email: str) -> str:
    from app.services.login_limiter import _digest, normalize_account
    return _digest("acct", normalize_account(email))


# ---------------------------------------------------------------------------
# Secondary per-IP bucket
# ---------------------------------------------------------------------------
class TestIpBucket:
    async def test_ip_bucket_limits_spraying_many_accounts(self, make_ip_client, store, clock):
        sprayer, bystander = make_ip_client("203.0.113.66"), make_ip_client("198.51.100.7")
        for i in range(100):
            assert (await login(sprayer, f"u{i}@example.com", "wrong-password")).status_code == 401
        res = await login(sprayer, "fresh-account@example.com", "wrong-password")
        assert res.status_code == 429 and res.json() == {"detail": RATE_LIMITED_DETAIL}
        assert res.headers["Retry-After"] == "3"
        assert (await login(bystander, "fresh-account@example.com", "wrong-password")).status_code == 401
        clock.advance(3)
        assert (await login(sprayer, "fresh-account@example.com", "wrong-password")).status_code == 401

    async def test_ip_rejection_does_not_drain_the_account(self, make_ip_client, store):
        c = make_ip_client("203.0.113.66")
        for i in range(100):
            await login(c, f"u{i}@example.com", "wrong-password")
        for _ in range(10):
            assert (await login(c, "target@example.com", "wrong-password")).status_code == 429
        assert store.peek("acct:" + _acct_digest("target@example.com")) is None

    async def test_trusted_header_identifies_clients_and_xff_is_ignored(self, client, store, monkeypatch):
        monkeypatch.setattr(settings, "CLIENT_IP_HEADER", "CF-Connecting-IP")
        for i in range(100):
            # A forged X-Forwarded-For must not buy a fresh bucket.
            await login(client, f"u{i}@example.com", "x" * 8,
                        headers={"CF-Connecting-IP": "203.0.113.5", "X-Forwarded-For": f"10.0.0.{i}"})
        blocked = await login(client, "z@example.com", "x" * 8, headers={"CF-Connecting-IP": "203.0.113.5"})
        other = await login(client, "z@example.com", "x" * 8, headers={"CF-Connecting-IP": "203.0.113.6"})
        assert blocked.status_code == 429 and other.status_code == 401

    async def test_ipv6_clients_are_grouped_by_64(self, make_ip_client, store):
        for i in range(100):
            await login(make_ip_client(f"2001:db8:1:2::{i + 1:x}"), f"u{i}@example.com", "wrong-password")
        assert (await login(make_ip_client("2001:db8:1:2::ffff"), "z@example.com", "x" * 8)).status_code == 429
        assert (await login(make_ip_client("2001:db8:1:3::1"), "z@example.com", "x" * 8)).status_code == 401

    def test_auto_mode_disables_ip_bucket_behind_unknown_proxy_in_production(self, monkeypatch):
        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        monkeypatch.setattr(settings, "CLIENT_IP_HEADER", "")
        assert settings.login_ip_limit_active is False
        monkeypatch.setattr(settings, "CLIENT_IP_HEADER", "CF-Connecting-IP")
        assert settings.login_ip_limit_active is True
        monkeypatch.setattr(settings, "LOGIN_IP_LIMIT", "off")
        assert settings.login_ip_limit_active is False


# ---------------------------------------------------------------------------
# Observability + configuration
# ---------------------------------------------------------------------------
class TestLoggingAndConfig:
    async def test_rate_limit_log_is_redacted_and_throttled(self, client, store, caplog):
        caplog.set_level(logging.WARNING, logger="app.security.login")
        await register(client, "private.person@example.com")
        for _ in range(55):
            await login(client, "private.person@example.com", "Sup3r-Secret-Pw")
        lines = [r.getMessage() for r in caplog.records if r.name == "app.security.login"]
        assert len(lines) == 1 and "login rate limit triggered" in lines[0] and "scope=account" in lines[0]
        text = caplog.text.lower()
        for secret in ("private.person", "example.com", "sup3r-secret-pw", "127.0.0.1"):
            assert secret not in text

    @pytest.mark.parametrize("overrides", [
        {"LOGIN_IP_LIMIT": "sometimes"},
        {"RATE_LIMIT_BACKEND": "memcached"},
        {"RATE_LIMIT_BACKEND": "redis", "REDIS_URL": ""},
        {"LOGIN_BUCKET_CAPACITY": 0},
        {"LOGIN_BUCKET_REFILL_SECONDS": 0},
    ])
    def test_invalid_settings_are_rejected(self, overrides):
        with pytest.raises(ValueError):
            Settings(_env_file=None, **overrides)

    def test_defaults_match_the_policy(self):
        s = Settings(_env_file=None)
        assert (s.LOGIN_BUCKET_CAPACITY, s.LOGIN_BUCKET_REFILL_SECONDS) == (50, 1.2)
        assert s.RATE_LIMIT_BACKEND == "memory"
        assert BucketPolicy.from_seconds(50, 1.2) == BucketPolicy(50, 1200)


# ---------------------------------------------------------------------------
# Redis backend (atomic Lua) — real server when available
# ---------------------------------------------------------------------------
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def redis_url():
    url = os.environ.get("REDIS_TEST_URL")
    if url:
        yield url
        return
    binary = shutil.which("redis-server")
    if not binary:
        pytest.skip("redis-server not available (set REDIS_TEST_URL to run Redis tests)")
    port = _free_port()
    workdir = tempfile.mkdtemp()
    proc = subprocess.Popen(
        [binary, "--port", str(port), "--bind", "127.0.0.1", "--save", "", "--appendonly", "no", "--dir", workdir],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.05)
    yield f"redis://127.0.0.1:{port}/15"
    proc.terminate()
    proc.wait(timeout=5)
    shutil.rmtree(workdir, ignore_errors=True)


@pytest_asyncio.fixture
async def redis_client(redis_url):
    import redis.asyncio as aioredis

    client = aioredis.Redis.from_url(redis_url, socket_timeout=2)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


class TestRedisBackend:
    async def test_same_semantics_as_memory(self, redis_client, clock):
        r = RedisTokenBuckets(redis_client, prefix="t:", clock=clock)
        assert [(await r.take("a", ACCOUNT)).allowed for _ in range(50)] == [True] * 50     # Test 1
        d = await r.take("a", ACCOUNT)
        assert not d.allowed and d.retry_after_ms == 1200                                     # Test 2
        clock.advance(1.199)
        assert not (await r.take("a", ACCOUNT)).allowed
        clock.advance(0.001)
        assert (await r.take("a", ACCOUNT)).allowed                                           # Test 3
        assert not (await r.take("a", ACCOUNT)).allowed
        clock.advance(1.2)
        assert (await r.take("a", ACCOUNT)).allowed                                           # Test 4
        clock.advance(7200)
        assert [(await r.take("a", ACCOUNT)).allowed for _ in range(51)] == [True] * 50 + [False]  # Test 5
        assert (await r.take("b", ACCOUNT)).allowed                                           # Test 7

    async def test_matches_the_reference_algorithm_step_for_step(self, redis_client, clock):
        import random

        rng = random.Random(7)
        r = RedisTokenBuckets(redis_client, prefix="t:", clock=clock)
        m = MemoryTokenBuckets(clock=clock)
        for _ in range(400):
            clock.advance(rng.choice([0, 0, 0, 0.3, 0.6, 1.2, 1.5, 4, 70]))
            assert await r.take("k", ACCOUNT) == await m.take("k", ACCOUNT)

    async def test_6_lua_script_is_atomic_under_concurrency(self, redis_url, clock):
        import redis.asyncio as aioredis

        clients = [aioredis.Redis.from_url(redis_url) for _ in range(8)]
        try:
            await clients[0].flushdb()
            stores = [RedisTokenBuckets(c, prefix="t:", clock=clock) for c in clients]
            for _ in range(49):
                await stores[0].take("last", ACCOUNT)
            # Open every pooled connection first, so the 40 attempts really race
            # (otherwise connection handshakes serialise them by accident).
            await asyncio.gather(*(c.ping() for c in clients for _ in range(5)))
            results = await asyncio.gather(*(stores[i % 8].take("last", ACCOUNT) for i in range(40)))
            assert sum(d.allowed for d in results) == 1
        finally:
            for c in clients:
                await c.aclose()

    async def test_server_clock_mode_and_expiry(self, redis_client):
        r = RedisTokenBuckets(redis_client, prefix="t:")          # production mode: Redis TIME
        started = time.monotonic()
        results = [(await r.take("s", ACCOUNT)).allowed for _ in range(51)]
        assert results[:50] == [True] * 50
        if time.monotonic() - started < 1.0:                      # (a very slow host could earn a token)
            assert results[50] is False
        ttl = await redis_client.pttl("t:s")
        assert 0 < ttl <= 51 * 1200                                # key cleans itself up once full again
        stored = await redis_client.hgetall("t:s")
        assert set(stored) == {b"tokens", b"last"}                 # no raw identifiers stored

    async def test_login_endpoint_on_redis(self, client, redis_client, clock):
        login_limiter.use_store(RedisTokenBuckets(redis_client, prefix="login-rl:", clock=clock))
        await register(client, "user@example.com")
        for _ in range(50):
            assert (await login(client, "user@example.com", "wrong-password")).status_code == 401
        res = await login(client, "user@example.com", "wrong-password")
        assert res.status_code == 429 and res.headers["Retry-After"] == "2"
        keys = [k.decode() for k in await redis_client.keys("login-rl:*")]
        assert keys and not any("user" in k or "example" in k or "127.0.0.1" in k for k in keys)


class TestRedisFailover:
    async def test_falls_back_to_memory_when_redis_is_down(self, clock, caplog):
        import redis.asyncio as aioredis

        dead = aioredis.Redis.from_url(f"redis://user:hunter2@127.0.0.1:{_free_port()}/0",
                                       socket_timeout=0.2, socket_connect_timeout=0.2)
        try:
            caplog.set_level(logging.WARNING)
            store = FailoverTokenBuckets(RedisTokenBuckets(dead, prefix="t:"), MemoryTokenBuckets(clock=clock))
            results = [(await store.take("a", ACCOUNT)).allowed for _ in range(51)]
            assert results == [True] * 50 + [False]        # still enforced, per process
            warnings = [r for r in caplog.records if "rate-limit store unavailable" in r.getMessage()]
            assert len(warnings) == 1                       # warned once, not per request
            assert "hunter2" not in caplog.text and "127.0.0.1" not in caplog.text
        finally:
            await dead.aclose()
