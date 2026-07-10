"""In-memory rate limiter for the public /v1/demo/generate endpoint."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock
from typing import Deque


class DemoRateLimiter:
    """Fixed-window request counter per client IP."""

    def __init__(self, *, limit: int, window_seconds: int = 3600) -> None:
        self.limit = max(1, limit)
        self.window_seconds = max(60, window_seconds)
        self._hits: dict[str, Deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, client_ip: str) -> tuple[bool, int]:
        """Return (allowed, retry_after_seconds)."""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            bucket = self._hits[client_ip]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self.limit:
                retry = int(self.window_seconds - (now - bucket[0])) + 1
                return False, max(1, retry)
            bucket.append(now)
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
