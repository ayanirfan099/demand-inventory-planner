"""In-process sliding-window rate limiting.

Sufficient for a single API process (the documented v1 deployment). In a multi-replica
deployment this must move to Redis; ``docs/operations.md`` records that constraint and the
limiter fails closed on its own accounting errors rather than silently allowing traffic.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from ..config import settings
from ..errors import RateLimitedError


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_seconds: int) -> None:
        """Raise :class:`RateLimitedError` when ``key`` exceeds ``limit`` per window."""

        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            bucket = self._events[key]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = int(bucket[0] + window_seconds - now) + 1
                raise RateLimitedError(
                    f"Rate limit reached for this action. Try again in {retry_after}s.",
                    details={"retry_after_seconds": retry_after},
                )
            bucket.append(now)

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


limiter = SlidingWindowLimiter()


def enforce(bucket: str, limit: int, *, window_seconds: int | None = None) -> None:
    limiter.check(bucket, limit, window_seconds or settings.rate_limit_window_seconds)
