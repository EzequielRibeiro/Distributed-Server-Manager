#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dashboard"))

from customer_security import SlidingWindowRateLimiter


def test_rate_limiter_blocks_and_recovers_after_window():
    now = [100.0]
    limiter = SlidingWindowRateLimiter(clock=lambda: now[0])
    assert limiter.check("recovery", "127.0.0.1", limit=2, window_seconds=60).allowed
    assert limiter.check("recovery", "127.0.0.1", limit=2, window_seconds=60).allowed
    blocked = limiter.check("recovery", "127.0.0.1", limit=2, window_seconds=60)
    assert not blocked.allowed
    assert blocked.retry_after > 0
    now[0] = 161.0
    assert limiter.check("recovery", "127.0.0.1", limit=2, window_seconds=60).allowed


def test_rate_limit_buckets_and_identities_are_isolated():
    limiter = SlidingWindowRateLimiter(clock=lambda: 10.0)
    assert limiter.check("register", "a", limit=1, window_seconds=60).allowed
    assert not limiter.check("register", "a", limit=1, window_seconds=60).allowed
    assert limiter.check("register", "b", limit=1, window_seconds=60).allowed
    assert limiter.check("recovery", "a", limit=1, window_seconds=60).allowed
