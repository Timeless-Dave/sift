"""API keys, admin checks, rate limiting and upload sniffing."""

from __future__ import annotations

import hashlib
import hmac
import math
import secrets
import struct
import threading
import time
from collections import deque

from .errors import Forbidden, InvalidInput, RateLimited, TooLarge

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
