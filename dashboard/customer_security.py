#!/usr/bin/env python3
"""Security primitives for customer-facing HTTP surfaces."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after: int = 0


class SlidingWindowRateLimiter:
    """Small in-process limiter suitable for the dashboard HTTP process."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._events: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def check(self, bucket: str, key: str, *, limit: int, window_seconds: int) -> RateLimitDecision:
        now = self._clock()
        cutoff = now - max(1, int(window_seconds))
        identity = (str(bucket), str(key))
        with self._lock:
            events = self._events[identity]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= max(1, int(limit)):
                retry_after = max(1, int(events[0] + window_seconds - now) + 1)
                return RateLimitDecision(False, retry_after)
            events.append(now)
            return RateLimitDecision(True, 0)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


customer_rate_limiter = SlidingWindowRateLimiter()


def remote_identity(handler) -> str:
    """Use the TCP peer address; do not trust spoofable forwarding headers."""
    address = getattr(handler, "client_address", None)
    if isinstance(address, tuple) and address:
        return str(address[0])
    return "unknown"
