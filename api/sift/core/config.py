"""Runtime settings, read once from environment variables (see .env.example)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

log = logging.getLogger("sift.config")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _int(name: str, default: int) -> int:
    raw = _env(name)
    try:
        return int(raw) if raw else default
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


@dataclass(frozen=True)
class Limits:
    max_image_bytes: int = field(default_factory=lambda: _int("SIFT_MAX_IMAGE_BYTES", 12 * 1024 * 1024))
    max_audio_bytes: int = field(default_factory=lambda: _int("SIFT_MAX_AUDIO_BYTES", 8 * 1024 * 1024))
    max_json_bytes: int = field(default_factory=lambda: _int("SIFT_MAX_JSON_BYTES", 2 * 1024 * 1024))
    max_user_text: int = field(default_factory=lambda: _int("SIFT_MAX_USER_TEXT", 500))
    max_history: int = 12
    max_frames_per_colour: int = 60
    max_colours: int = 32
    # Requests per minute per client.
    rate_public: int = field(default_factory=lambda: _int("SIFT_RATE_PUBLIC", 30))
    rate_keyed: int = field(default_factory=lambda: _int("SIFT_RATE_KEYED", 240))
    rate_agent: int = field(default_factory=lambda: _int("SIFT_RATE_AGENT", 20))


@dataclass(frozen=True)
class Settings:
    env: str = field(default_factory=lambda: _env("SIFT_ENV", "development"))
    meta_api_key: str = field(default_factory=lambda: _env("MODEL_API_KEY"))
    meta_base_url: str = field(default_factory=lambda: _env("META_BASE_URL", "https://api.meta.ai/v1"))
    chat_model: str = field(default_factory=lambda: _env("SIFT_CHAT_MODEL", "muse-spark-1.3"))
    transcribe_model: str = field(default_factory=lambda: _env("SIFT_TRANSCRIBE_MODEL", "muse-voice-transcribe-1.0"))
    # Muse Spark reasons before it answers, and reasoning tokens count against max_tokens.
    reasoning_effort: str = field(default_factory=lambda: _env("SIFT_REASONING_EFFORT", "minimal"))
    sam_model: str = field(default_factory=lambda: _env("SIFT_SAM_MODEL", "sam-3.1"))
    # SAM 3.1 segments over the Responses API (dev.meta.ai/docs/sam/overview); Sift falls
    # back to its own segmentation whenever the call fails.
    sam_path: str = field(default_factory=lambda: _env("SIFT_SAM_PATH", "/responses"))
    transcribe_path: str = field(default_factory=lambda: _env("SIFT_TRANSCRIBE_PATH", "/asr/transcribe"))
    db_path: Path = field(default_factory=lambda: Path(_env("SIFT_DB", "sift.db")))
    # Empty means the in-process limiter (one worker); set to redis://... to share limits across workers.
    redis_url: str = field(default_factory=lambda: _env("SIFT_REDIS_URL"))
    require_api_key: bool = field(default_factory=lambda: _env("SIFT_REQUIRE_KEY", "0") == "1")
    protect_calibration: bool = field(default_factory=lambda: _env("SIFT_PROTECT_CALIBRATION", "0") == "1")
    admin_token: str = field(default_factory=lambda: _env("SIFT_ADMIN_TOKEN"))
    trust_proxy: bool = field(default_factory=lambda: _env("SIFT_TRUST_PROXY", "0") == "1")
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(o.strip() for o in _env("SIFT_CORS", "*").split(",") if o.strip())
    )
    limits: Limits = field(default_factory=Limits)

    @property
    def agent_online(self) -> bool:
        return bool(self.meta_api_key)

    @property
    def production(self) -> bool:
        return self.env == "production"

    def validate(self) -> None:
        """Fail fast on settings that would make the service unsafe or broken."""
        if not self.meta_base_url.startswith("https://"):
            raise ValueError("META_BASE_URL must use https.")
        if self.production:
            if "*" in self.cors_origins:
                raise ValueError("SIFT_CORS must list the app's origins in production, not '*'.")
            if self.admin_token and len(self.admin_token) < 24:
                raise ValueError("SIFT_ADMIN_TOKEN must be at least 24 characters.")
        if not self.meta_api_key:
            log.warning("MODEL_API_KEY not set: the Lab Agent runs offline.")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    s.validate()
    return s
