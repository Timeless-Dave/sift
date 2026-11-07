"""API keys, admin checks, rate limiting and upload sniffing."""

from __future__ import annotations

import hashlib
import hmac
import logging
import math
import secrets
import struct
import threading
import time
from collections import deque

from .errors import Forbidden, InvalidInput, RateLimited, TooLarge

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


MAX_IMAGE_PIXELS = 50_000_000  # a 48 MP phone photo fits; a decompression bomb doesn't


def image_size(raw: bytes) -> tuple[int, int] | None:
    """(width, height) from a JPEG, PNG or WebP header, without decoding pixels. None if not found."""
    try:
        if raw.startswith(b"\x89PNG") and raw[12:16] == b"IHDR":
            return struct.unpack(">II", raw[16:24])
        if raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
            chunk = raw[12:16]
            if chunk == b"VP8X":
                return 1 + int.from_bytes(raw[24:27], "little"), 1 + int.from_bytes(raw[27:30], "little")
            if chunk == b"VP8L":
                b = int.from_bytes(raw[21:25], "little")
                return 1 + (b & 0x3FFF), 1 + ((b >> 14) & 0x3FFF)
            if chunk == b"VP8 ":
                w, h = struct.unpack("<HH", raw[26:30])
                return w & 0x3FFF, h & 0x3FFF
            return None
        if raw.startswith(b"\xff\xd8"):
            i = 2
            while i + 9 < len(raw):
                if raw[i] != 0xFF:
                    i += 1
                    continue
                marker = raw[i + 1]
                if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7 or marker == 0xFF:
                    i += 1 if marker == 0xFF else 2
                    continue
                length = struct.unpack(">H", raw[i + 2:i + 4])[0]
                if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):  # start of frame
                    h, w = struct.unpack(">HH", raw[i + 5:i + 9])
                    return w, h
                i += 2 + length
    except struct.error:
        return None
    return None


def check_pixels(raw: bytes, limit: int = MAX_IMAGE_PIXELS) -> None:
    """Refuse decompression bombs before decoding: compressed size says nothing about pixel count."""
    size = image_size(raw)
    if size is None:
        raise InvalidInput("The upload isn't a readable image.")
    w, h = size
    if w * h > limit:
        raise TooLarge(f"The photo has too many pixels. Use a photo under {limit // 1_000_000} megapixels.")


def sniff_audio(raw: bytes) -> str:
    if len(raw) > 12 and raw[4:8] == b"ftyp":
        return "audio/mp4"
    for magic, mime in _AUDIO_MAGIC:
        if raw.startswith(magic):
            return mime
    raise InvalidInput("Upload WebM, Ogg, MP4, WAV or MP3 audio.")
