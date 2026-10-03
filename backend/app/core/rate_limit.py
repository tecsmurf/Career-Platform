"""
Minimal in-process sliding-window rate limiter.

Good enough for a single-instance deployment (Render free tier runs one
process). For multi-instance deployments, back this with a shared store.
Sync throttling does NOT rely on this — it uses an atomic DB claim + cooldown,
which works across instances.

Memory is bounded: idle keys are swept periodically, and at most ``max_keys``
keys are tracked (least recently used keys are dropped first), so callers
can key on client-supplied values such as email addresses.
"""
import threading
import time
from collections import OrderedDict, deque


class SlidingWindowLimiter:
    SWEEP_EVERY = 1024

    def __init__(self, max_calls: int, window_seconds: float, max_keys: int = 50_000):
        self.max_calls = max_calls
        self.window = window_seconds
        self.max_keys = max_keys
        self._hits: "OrderedDict[object, deque]" = OrderedDict()
        self._lock = threading.Lock()
        self._ops = 0

    def _sweep(self, now: float) -> None:
        stale = [k for k, q in self._hits.items() if not q or now - q[-1] >= self.window]
        for k in stale:
            del self._hits[k]

    def hit(self, key) -> int | None:
        """Record an attempt. Returns None if allowed, else seconds until retry."""
        now = time.monotonic()
        with self._lock:
            self._ops += 1
            if self._ops % self.SWEEP_EVERY == 0:
                self._sweep(now)
            q = self._hits.get(key)
            if q is None:
                q = self._hits[key] = deque()
                while len(self._hits) > self.max_keys:
                    self._hits.popitem(last=False)
            else:
                self._hits.move_to_end(key)
            while q and now - q[0] >= self.window:
                q.popleft()
            if len(q) >= self.max_calls:
                return max(1, int(self.window - (now - q[0])) + 1)
            q.append(now)
            return None

    def __len__(self) -> int:
        return len(self._hits)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
            self._ops = 0
