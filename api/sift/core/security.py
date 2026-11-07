"""API keys, admin checks, rate limiting and upload sniffing."""

from __future__ import annotations

import hashlib
import hmac
import logging
import math
import secrets
import threading
import time
from collections import deque

from .errors import Forbidden, InvalidInput, RateLimited

log = logging.getLogger("sift.security")

KEY_PREFIX = "sift_"


def new_api_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def hash_key(key: str) -> str:
    """Keys are stored as SHA-256 hashes; the plaintext is shown once, at creation."""
    return hashlib.sha256(key.encode()).hexdigest()


def check_admin(supplied: str | None, expected: str) -> None:
    if not expected:
        raise Forbidden("Key management is disabled on this server.")
    if not supplied or not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise Forbidden("Admin token required.")


class RateLimiter:
    """Sliding one-minute window per (bucket, identity). In-process only: run one API worker
    per instance, or move this to Redis when scaling out."""

    def __init__(self, window: float = 60.0):
        self.window = window
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, bucket: str, identity: str, limit: int) -> None:
        if limit <= 0:
            return
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault((bucket, identity), deque())
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= limit:
                retry = max(1, math.ceil(self.window - (now - q[0])))
                raise RateLimited(f"Too many requests. Try again in {retry} seconds.", retry_after=retry)
            q.append(now)
            if len(self._hits) > 50_000:  # bound memory under abuse
                self._hits = {k: v for k, v in self._hits.items() if v and now - v[-1] <= self.window}


# Sliding window over a sorted set, atomically: drop hits older than the window, count the
# rest, and record the new hit only when under the limit. Returns {count, retry_after}.
_WINDOW_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
    local old = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local retry = 1
    if #old == 2 then
        retry = math.ceil(old[2] + window - now)
        if retry < 1 then retry = 1 end
    end
    return {count, retry}
end
redis.call('ZADD', key, now, member)
redis.call('PEXPIRE', key, math.ceil(window * 1000) + 1000)
return {count + 1, 0}
"""


class RedisRateLimiter(RateLimiter):
    """Sliding window shared across workers via Redis. Fails open to the in-process limiter."""

    def __init__(self, client, window: float = 60.0):
        super().__init__(window)
        self._client = client
        self._warned = False

    @classmethod
    def from_url(cls, url: str, window: float = 60.0) -> RedisRateLimiter:
        import redis  # lazy: the package is optional, only needed when SIFT_REDIS_URL is set

        return cls(redis.from_url(url, socket_connect_timeout=2, socket_timeout=2), window)

    def hit(self, bucket: str, identity: str, limit: int) -> None:
        if limit <= 0:
            return
        now = time.time()  # wall clock: monotonic clocks are not comparable across workers
        member = f"{now:.6f}:{secrets.token_hex(4)}"
        try:
            _, retry = self._client.eval(_WINDOW_SCRIPT, 1, f"sift:rl:{bucket}:{identity}", now, self.window,
                                         limit, member)
        except Exception as exc:  # Redis down: stay up on the in-process window, warn once
            with self._lock:
                warned, self._warned = self._warned, True
            if not warned:
                log.warning("Redis unavailable; failing open to the in-process rate limiter (%s).", type(exc).__name__)
            super().hit(bucket, identity, limit)
            return
        if retry:
            retry = int(retry)
            raise RateLimited(f"Too many requests. Try again in {retry} seconds.", retry_after=retry)


_IMAGE_MAGIC = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"RIFF", "image/webp"),
)
_AUDIO_MAGIC = (
    (b"\x1aE\xdf\xa3", "audio/webm"),
    (b"OggS", "audio/ogg"),
    (b"RIFF", "audio/wav"),
    (b"ID3", "audio/mpeg"),
    (b"\xff\xfb", "audio/mpeg"),
)


def sniff_image(raw: bytes) -> str:
    for magic, mime in _IMAGE_MAGIC:
        if raw.startswith(magic) and (mime != "image/webp" or raw[8:12] == b"WEBP"):
            return mime
    raise InvalidInput("Upload a JPEG, PNG or WebP photo.")


def sniff_audio(raw: bytes) -> str:
    if len(raw) > 12 and raw[4:8] == b"ftyp":
        return "audio/mp4"
    for magic, mime in _AUDIO_MAGIC:
        if raw.startswith(magic):
            return mime
    raise InvalidInput("Upload WebM, Ogg, MP4, WAV or MP3 audio.")
