"""API keys, admin checks, rate limiting and upload sniffing."""

from __future__ import annotations

import hashlib
import hmac
import math
import secrets
import threading
import time
from collections import deque

from .errors import Forbidden, InvalidInput, RateLimited

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
