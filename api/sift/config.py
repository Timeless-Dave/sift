"""Runtime settings, read from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Settings:
    meta_api_key: str = field(default_factory=lambda: _env("MODEL_API_KEY"))
    meta_base_url: str = field(default_factory=lambda: _env("META_BASE_URL", "https://api.meta.ai/v1"))
    chat_model: str = field(default_factory=lambda: _env("SIFT_CHAT_MODEL", "muse-spark-1.3"))
    transcribe_model: str = field(default_factory=lambda: _env("SIFT_TRANSCRIBE_MODEL", "muse-voice-transcribe-1.0"))
    sam_model: str = field(default_factory=lambda: _env("SIFT_SAM_MODEL", "sam-3.1"))
    # Path of the SAM 3.1 endpoint under the base URL. Check it against dev.meta.ai/docs/models
    # before relying on segmentation; Sift falls back to its own window mask when the call fails.
    sam_path: str = field(default_factory=lambda: _env("SIFT_SAM_PATH", "/segment"))
    db_path: Path = field(default_factory=lambda: Path(_env("SIFT_DB", "sift.db")))
    require_api_key: bool = field(default_factory=lambda: _env("SIFT_REQUIRE_KEY", "0") == "1")
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(o for o in _env("SIFT_CORS", "*").split(",") if o)
    )

    @property
    def agent_online(self) -> bool:
        return bool(self.meta_api_key)


def get_settings() -> Settings:
    return Settings()
