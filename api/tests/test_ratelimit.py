"""Redis-backed rate limiter, exercised against a small in-memory fake (no server needed)."""

import logging
import math
import time

import pytest

from sift.core.errors import RateLimited
from sift.core.security import RedisRateLimiter


class FakeRedis:
    """Emulates the limiter's one Redis call (EVAL of the window script) with sorted sets."""

    def __init__(self):
        self.zsets: dict[str, dict[str, float]] = {}

    def eval(self, _script, _numkeys, key, now, window, limit, member):
        now, window, limit = float(now), float(window), int(limit)
        z = self.zsets.setdefault(key, {})
        for m in [m for m, s in z.items() if s <= now - window]:
            del z[m]
        if len(z) >= limit:
            return [len(z), max(1, math.ceil(min(z.values()) + window - now))]
        z[member] = now
        return [len(z), 0]


class FailingRedis:
    def eval(self, *args, **kwargs):
        raise ConnectionError("redis down")


def test_limit_reached():
    limiter = RedisRateLimiter(FakeRedis())
    for _ in range(3):
        limiter.hit("api", "u", 3)
    with pytest.raises(RateLimited):
        limiter.hit("api", "u", 3)


def test_retry_after_at_least_one():
    limiter = RedisRateLimiter(FakeRedis())
    with pytest.raises(RateLimited) as excinfo:
        for _ in range(4):
            limiter.hit("api", "u", 3)
    assert excinfo.value.extra["retry_after"] >= 1


def test_window_expiry():
    limiter = RedisRateLimiter(FakeRedis(), window=0.2)
    limiter.hit("api", "u", 1)
    with pytest.raises(RateLimited):
        limiter.hit("api", "u", 1)
    time.sleep(0.25)
    limiter.hit("api", "u", 1)


def test_fail_open_uses_in_process_limiter(caplog):
    limiter = RedisRateLimiter(FailingRedis())
    with caplog.at_level(logging.WARNING, logger="sift.security"):
        limiter.hit("api", "u", 2)
        limiter.hit("api", "u", 2)
        with pytest.raises(RateLimited):  # enforced locally; the Redis error never leaks
            limiter.hit("api", "u", 2)
        with pytest.raises(RateLimited):
            limiter.hit("api", "u", 2)
    assert sum("Redis unavailable" in r.message for r in caplog.records) == 1
