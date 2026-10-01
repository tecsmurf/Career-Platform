"""
Minimal in-process sliding-window rate limiter.

Good enough for a single-instance deployment (Render free tier runs one
process). For multi-instance deployments, back this with a shared store.
Sync throttling does NOT rely on this — it uses an atomic DB claim + cooldown,
which works across instances.
"""
import threading
import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    def __init__(self, max_calls: int, window_seconds: float):
        self.max_calls = max_calls
        self.window = window_seconds
        self._hits: dict[object, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key) -> int | None:
        """Record an attempt. Returns None if allowed, else seconds until retry."""
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] >= self.window:
                q.popleft()
            if len(q) >= self.max_calls:
                return max(1, int(self.window - (now - q[0])) + 1)
            q.append(now)
            return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
