"""
Token buckets — the algorithm and its two storage backends.

Algorithm (integer milliseconds, so 1.2 s refills never drift through
floating-point error):

    elapsed     = now - last_refill
    add         = floor(elapsed / refill_ms)
    tokens      = min(capacity, tokens + add)
    last_refill = last_refill + add * refill_ms
    if tokens == capacity: last_refill = now     # a full bucket banks no partial credit
    if tokens >= 1: tokens -= 1 → allowed
    else          → rejected, retry in (refill_ms - (now - last_refill)) ms

A brand-new bucket starts full. Tokens never exceed `capacity`; there is no
fixed-window reset — a drained bucket earns back exactly one token per
`refill_ms`.

Backends
--------
MemoryTokenBuckets  In-process. The read-modify-write runs under a lock and
                    reads a monotonic clock, so it is atomic and immune to
                    wall-clock jumps. Correct for ONE process.
RedisTokenBuckets   Shared by every process/instance. The whole operation is
                    a single Lua script, which Redis executes atomically. The
                    clock is the Redis server's own (one clock for all app
                    instances — per-process monotonic clocks are not
                    comparable across machines); a backwards jump is clamped
                    so it can never mint tokens.
FailoverTokenBuckets
                    Uses Redis and falls back to the in-process store if
                    Redis errors or times out, so a Redis outage never turns
                    into a login outage, while each process stays protected.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)

Clock = Callable[[], int]  # returns milliseconds


def monotonic_ms() -> int:
    return time.monotonic_ns() // 1_000_000


@dataclass(frozen=True)
class BucketPolicy:
    capacity: int
    refill_ms: int  # one token is added every refill_ms

    @classmethod
    def from_seconds(cls, capacity: int, refill_seconds: float) -> "BucketPolicy":
        return cls(capacity=int(capacity), refill_ms=max(1, round(refill_seconds * 1000)))

    @property
    def full_refill_ms(self) -> int:
        return self.capacity * self.refill_ms


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after_ms: int = 0


def take_token(tokens: int, last_ms: int, now_ms: int, policy: BucketPolicy) -> tuple[int, int, Decision]:
    """Pure token-bucket step. Returns the new (tokens, last_refill) and the decision."""
    if now_ms < last_ms:  # clock moved backwards: resync, never grant credit for it
        last_ms = now_ms
    add = (now_ms - last_ms) // policy.refill_ms
    if add > 0:
        tokens = min(policy.capacity, tokens + add)
        last_ms += add * policy.refill_ms
    if tokens >= policy.capacity:
        tokens = policy.capacity
        last_ms = now_ms
    if tokens >= 1:
        return tokens - 1, last_ms, Decision(True)
    return tokens, last_ms, Decision(False, policy.refill_ms - (now_ms - last_ms))


class MemoryTokenBuckets:
    """Thread-safe in-process buckets with bounded memory.

    Entries that would be full again are indistinguishable from fresh buckets,
    so they are pruned. A hard cap evicts least-recently-used entries (those
    closest to full) if a flood of distinct keys ever outpaces pruning.
    """

    def __init__(self, clock: Clock = monotonic_ms, max_keys: int = 100_000, prune_every_ms: int = 30_000):
        self.clock = clock
        self.max_keys = max_keys
        self.prune_every_ms = prune_every_ms
        # key -> (tokens, last_refill_ms, full_again_at_ms)
        self._buckets: OrderedDict[str, tuple[int, int, int]] = OrderedDict()
        self._lock = threading.Lock()
        self._last_prune: int | None = None

    async def take(self, key: str, policy: BucketPolicy) -> Decision:
        return self.take_sync(key, policy)

    def take_sync(self, key: str, policy: BucketPolicy) -> Decision:
        with self._lock:
            now = self.clock()  # read inside the lock so `now` never goes backwards per key
            state = self._buckets.get(key)
            tokens, last = (state[0], state[1]) if state else (policy.capacity, now)
            tokens, last, decision = take_token(tokens, last, now, policy)
            full_at = last + (policy.capacity - tokens) * policy.refill_ms
            self._buckets[key] = (tokens, last, full_at)
            self._buckets.move_to_end(key)
            self._maintain(now)
            return decision

    def _maintain(self, now: int) -> None:
        if self._last_prune is None or now - self._last_prune >= self.prune_every_ms or len(self._buckets) > self.max_keys:
            self._last_prune = now
            for k in [k for k, v in self._buckets.items() if v[2] <= now]:
                del self._buckets[k]
            while len(self._buckets) > self.max_keys:
                self._buckets.popitem(last=False)

    def peek(self, key: str) -> int | None:
        """Stored token count (tests/diagnostics only; not refilled)."""
        with self._lock:
            state = self._buckets.get(key)
            return state[0] if state else None

    def __len__(self) -> int:
        return len(self._buckets)

    async def reset(self) -> None:
        self.reset_sync()

    def reset_sync(self) -> None:
        with self._lock:
            self._buckets.clear()
            self._last_prune = None


# KEYS[1] = bucket key
# ARGV[1] = capacity, ARGV[2] = refill_ms, ARGV[3] = now_ms ('' → Redis server clock)
# Returns {allowed (0|1), retry_after_ms}
_TAKE_LUA = """
local capacity = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local now
if ARGV[3] ~= nil and ARGV[3] ~= '' then
  now = tonumber(ARGV[3])
else
  if redis.replicate_commands then pcall(redis.replicate_commands) end
  local t = redis.call('TIME')
  now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
end
local state = redis.call('HMGET', KEYS[1], 'tokens', 'last')
local tokens = tonumber(state[1])
local last = tonumber(state[2])
if tokens == nil or last == nil then
  tokens = capacity
  last = now
end
if now < last then last = now end
local add = math.floor((now - last) / refill)
if add > 0 then
  tokens = math.min(capacity, tokens + add)
  last = last + add * refill
end
if tokens >= capacity then
  tokens = capacity
  last = now
end
local allowed = 0
local wait = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
else
  wait = refill - (now - last)
end
redis.call('HSET', KEYS[1], 'tokens', string.format('%d', tokens), 'last', string.format('%d', last))
redis.call('PEXPIRE', KEYS[1], (capacity - tokens) * refill + refill)
return {allowed, wait}
"""


class RedisTokenBuckets:
    """Atomic shared buckets: one Lua script per attempt (EVALSHA, cached)."""

    def __init__(self, client, prefix: str = "rl:", clock: Clock | None = None):
        self.client = client
        self.prefix = prefix
        self.clock = clock  # None → Redis server time (production); tests inject a fake clock
        self._script = client.register_script(_TAKE_LUA)

    async def take(self, key: str, policy: BucketPolicy) -> Decision:
        now = "" if self.clock is None else str(self.clock())
        allowed, wait = await self._script(keys=[self.prefix + key], args=[policy.capacity, policy.refill_ms, now])
        return Decision(bool(int(allowed)), int(wait))

    async def reset(self) -> None:
        async for k in self.client.scan_iter(match=self.prefix + "*", count=500):
            await self.client.delete(k)


class FailoverTokenBuckets:
    """Redis first; on any Redis error fall back to in-process buckets."""

    WARN_EVERY_MS = 60_000

    def __init__(self, primary: RedisTokenBuckets, fallback: MemoryTokenBuckets):
        self.primary = primary
        self.fallback = fallback
        self._last_warn: int | None = None

    async def take(self, key: str, policy: BucketPolicy) -> Decision:
        try:
            return await self.primary.take(key, policy)
        except Exception as exc:  # connection refused, timeout, auth, script error…
            now = monotonic_ms()
            if self._last_warn is None or now - self._last_warn >= self.WARN_EVERY_MS:
                self._last_warn = now
                # Exception type only: Redis error text can include the server URL.
                logger.warning("rate-limit store unavailable (%s); using in-process buckets", type(exc).__name__)
            return await self.fallback.take(key, policy)

    async def reset(self) -> None:
        await self.fallback.reset()
        try:
            await self.primary.reset()
        except Exception:
            pass
