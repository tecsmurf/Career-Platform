"""
Login rate limiting.

Policy (documented in README → "Login rate limiting"):

* Per-account token bucket — the primary control. Key: the submitted login
  identifier normalised with `.strip().lower()`, so "Alice@X.com " and
  "alice@x.com" share one bucket. The key is used whether or not an account
  exists, so throttling behaves identically for real and unknown emails and
  reveals nothing about account existence.
  Capacity 50, +1 token every 1.2 s (≈41.7 sustained attempts / minute).

* Every login request that reaches credential verification consumes one
  token — successful logins included. A token is consumed BEFORE bcrypt runs,
  which is what makes the bucket a hard ceiling on password checks. There is
  no lockout state: a drained bucket earns a token back every 1.2 s, so even
  a user who signs in 50 times in a burst waits at most ~1.2 s for the next
  attempt. Nothing can lock an account permanently.

* Per-client-IP bucket — defence in depth (100 burst, +1 / 3 s). It limits
  spraying many accounts from one address, and because it refills slower than
  an account bucket, a single address cannot hold someone's account drained
  for long. Checked first; a request rejected by it does not touch the
  account bucket.

Identifiers are stored and logged only as truncated HMAC-SHA256 digests keyed
with SECRET_KEY: raw emails/IPs never reach Redis or the logs.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
import math
import threading

from fastapi import Request

from app.core.config import settings
from app.core.token_bucket import (
    BucketPolicy,
    FailoverTokenBuckets,
    MemoryTokenBuckets,
    RedisTokenBuckets,
    monotonic_ms,
)

logger = logging.getLogger("app.security.login")

RATE_LIMITED_DETAIL = "Too many login attempts. Please try again shortly."


def normalize_account(identifier: str) -> str:
    return (identifier or "").strip().lower()


def _digest(scope: str, value: str) -> str:
    mac = hmac.new(settings.SECRET_KEY.encode(), f"{scope}:{value}".encode(), hashlib.sha256)
    return mac.hexdigest()[:32]


def _ip_bucket_value(raw: str | None) -> str | None:
    """Canonical IP for bucketing; IPv6 is grouped by /64 (one subscriber)."""
    if not raw:
        return None
    try:
        ip = ipaddress.ip_address(raw.strip())
    except ValueError:
        return None
    if ip.version == 6:
        if ip.ipv4_mapped:
            return str(ip.ipv4_mapped)
        return str(ipaddress.ip_network(f"{ip}/64", strict=False).network_address) + "/64"
    return str(ip)


def client_ip(request: Request) -> str | None:
    """The client address used for the IP bucket.

    With CLIENT_IP_HEADER configured (e.g. CF-Connecting-IP behind Cloudflare),
    that header wins; it must be one the edge proxy overwrites. Otherwise the
    socket peer is used. X-Forwarded-For is never trusted implicitly: its
    leftmost entries are client-controlled.
    """
    header = settings.CLIENT_IP_HEADER.strip()
    if header:
        value = request.headers.get(header)
        if value:
            ip = _ip_bucket_value(value.split(",")[0])
            if ip:
                return ip
    return _ip_bucket_value(request.client.host if request.client else None)


class LoginRateLimiter:
    LOG_EVERY_MS = 60_000

    def __init__(self, store=None):
        self._store = store
        self._store_lock = threading.Lock()
        self._logged: dict[str, int] = {}

    # -- store -----------------------------------------------------------
    @property
    def store(self):
        if self._store is None:
            with self._store_lock:
                if self._store is None:
                    self._store = self._build_store()
        return self._store

    @staticmethod
    def _build_store():
        memory = MemoryTokenBuckets()
        if settings.RATE_LIMIT_BACKEND.strip().lower() != "redis":
            if settings.is_production:
                logger.warning(
                    "login rate limiter is using in-process memory; set RATE_LIMIT_BACKEND=redis "
                    "if you run more than one worker or instance"
                )
            return memory
        import redis.asyncio as aioredis

        timeout = settings.RATE_LIMIT_REDIS_TIMEOUT_SECONDS
        client = aioredis.Redis.from_url(
            settings.REDIS_URL, socket_timeout=timeout, socket_connect_timeout=timeout,
        )
        return FailoverTokenBuckets(RedisTokenBuckets(client, prefix="login-rl:"), memory)

    def use_store(self, store) -> None:
        """Swap the bucket store (tests, or explicit wiring); clears log throttling."""
        self._store = store
        self._logged.clear()

    async def reset(self) -> None:
        self._logged.clear()
        if self._store is not None:
            await self._store.reset()

    # -- policy ----------------------------------------------------------
    @staticmethod
    def account_policy() -> BucketPolicy:
        return BucketPolicy.from_seconds(settings.LOGIN_BUCKET_CAPACITY, settings.LOGIN_BUCKET_REFILL_SECONDS)

    @staticmethod
    def ip_policy() -> BucketPolicy:
        return BucketPolicy.from_seconds(settings.LOGIN_IP_BUCKET_CAPACITY, settings.LOGIN_IP_BUCKET_REFILL_SECONDS)

    async def check(self, *, account: str, ip: str | None) -> int | None:
        """Consume one attempt. Returns None if allowed, else Retry-After seconds."""
        if not settings.LOGIN_RATE_LIMIT_ENABLED:
            return None
        if ip and settings.login_ip_limit_active:
            ip_key = "ip:" + _digest("ip", ip)
            decision = await self.store.take(ip_key, self.ip_policy())
            if not decision.allowed:
                self._log("ip", ip_key)
                return _retry_after_seconds(decision.retry_after_ms)
        acct_key = "acct:" + _digest("acct", normalize_account(account))
        decision = await self.store.take(acct_key, self.account_policy())
        if not decision.allowed:
            self._log("account", acct_key)
            return _retry_after_seconds(decision.retry_after_ms)
        return None

    def _log(self, scope: str, key: str) -> None:
        """One line per bucket per minute — enough to see an attack, not a log flood."""
        now = monotonic_ms()
        last = self._logged.get(key)
        if last is not None and now - last < self.LOG_EVERY_MS:
            return
        if len(self._logged) > 10_000:
            self._logged = {k: t for k, t in self._logged.items() if now - t < self.LOG_EVERY_MS}
        self._logged[key] = now
        logger.warning("login rate limit triggered: scope=%s subject=%s", scope, key.split(":", 1)[1][:12])


def _retry_after_seconds(wait_ms: int) -> int:
    # Whole seconds only (no unnecessary precision); at least 1.
    return max(1, math.ceil(wait_ms / 1000))


login_limiter = LoginRateLimiter()
