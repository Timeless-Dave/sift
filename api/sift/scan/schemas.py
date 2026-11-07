"""Wire format for instant scans (docs/scanner.md). The web mirror is web/src/sensors/types.ts.

Every sensor reading is a summary computed on the phone. Raw audio and video never reach the
server. Field limits here are the first line of input validation.
"""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Modality = Literal["torch", "screenlight", "acoustic", "vibration", "motion"]
SENSING_MODALITIES: tuple[str, ...] = ("torch", "screenlight", "acoustic", "vibration")  # motion is a gate only
MAX_BINS = 128
MAX_SPECTRUM = 64

Unit = Annotated[float, Field(ge=0.0, le=1.0)]
RGB = Annotated[list[Unit], Field(min_length=3, max_length=3)]


def _finite(values: list[float], what: str) -> list[float]:
    if not all(math.isfinite(v) for v in values):
        raise ValueError(f"{what} must be finite numbers")
    return values


class RGBStats(BaseModel):
    """Mean and spread of the centre region of the camera frame, sRGB 0..1."""
    mean: RGB
    std: RGB
    clipped: Unit = Field(description="Fraction of centre pixels at or near 255 in any channel")


class TorchCapture(BaseModel):
    off: RGBStats
    on: RGBStats | None = Field(default=None, description="Missing when the phone has no controllable torch")
    torch_available: bool


class ScreenlightCapture(BaseModel):
    frames: dict[str, Annotated[list[RGB], Field(min_length=1, max_length=60)]] = Field(max_length=32)


class AcousticCapture(BaseModel):
    sample_rate: int = Field(ge=8000, le=192000)
    bins_hz: list[float] = Field(min_length=8, max_length=MAX_BINS)
    response_db: list[float] = Field(min_length=8, max_length=MAX_BINS)
    noise_db: list[float] = Field(min_length=8, max_length=MAX_BINS)

    @field_validator("bins_hz")
    @classmethod
    def _bins(cls, v: list[float]) -> list[float]:
        _finite(v, "bins_hz")
        if any(not 100 <= f <= 24000 for f in v) or any(b <= a for a, b in zip(v, v[1:], strict=False)):
            raise ValueError("bins_hz must increase within 100-24000 Hz")
        return v

    @field_validator("response_db", "noise_db")
    @classmethod
    def _db(cls, v: list[float]) -> list[float]:
        _finite(v, "levels")
        if any(not -200 <= x <= 60 for x in v):
            raise ValueError("levels must be within -200..60 dB")
        return v

    @model_validator(mode="after")
    def _lengths(self) -> AcousticCapture:
        if not len(self.bins_hz) == len(self.response_db) == len(self.noise_db):
            raise ValueError("bins_hz, response_db and noise_db must have the same length")
        return self


class VibrationCapture(BaseModel):
    rate_hz: float = Field(ge=10, le=1000)
    rms_on: float = Field(ge=0, le=100)
    rms_off: float = Field(ge=0, le=100)
    spectrum: list[Annotated[float, Field(ge=0, le=1000)]] = Field(default_factory=list, max_length=MAX_SPECTRUM)
    vibrate_available: bool


class MotionCapture(BaseModel):
    max_rotation_dps: float = Field(ge=0, le=5000)
    accel_jitter: float = Field(ge=0, le=100)


class Capture(BaseModel):
    torch: TorchCapture | None = None
    screenlight: ScreenlightCapture | None = None
    acoustic: AcousticCapture | None = None
    vibration: VibrationCapture | None = None
    motion: MotionCapture | None = None

    @model_validator(mode="after")
    def _something(self) -> Capture:
        if not any(getattr(self, m) is not None for m in SENSING_MODALITIES):
            raise ValueError("capture needs at least one of torch, screenlight, acoustic, vibration")
        return self


ReferenceLabel = Literal["genuine", "adulterated", "cultured", "conventional"]


class ReferenceInfo(BaseModel):
    label: ReferenceLabel
    target: str | None = Field(default=None, max_length=64, pattern=r"^[a-z0-9-]+$")
    value: float | None = Field(default=None, ge=0, le=1_000_000)
    note: str = Field(default="", max_length=200)


class Product(BaseModel):
    barcode: str | None = Field(default=None, pattern=r"^[0-9]{6,14}$")


class ScanRequest(BaseModel):
    food: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")
    product: Product | None = None
    device: str = Field(default="unknown", min_length=1, max_length=80, pattern=r"^[\w .,()+\-/x]+$")
    mode: Literal["check", "reference"] = "check"
    reference: ReferenceInfo | None = None
    capture: Capture

    @model_validator(mode="after")
    def _reference(self) -> ScanRequest:
        if self.mode == "reference" and self.reference is None:
            raise ValueError("reference scans need a reference label")
        if self.mode == "check" and self.reference is not None:
            raise ValueError("check scans don't take a reference label")
        return self


# ---- response -------------------------------------------------------------------------------

class Problem(BaseModel):
    modality: Modality | Literal["scan"]
    code: str
    severity: Literal["reject", "warn"]
    message: str
    fix: str


class Quality(BaseModel):
    ok: bool
    problems: list[Problem] = Field(default_factory=list)


class Match(BaseModel):
    status: Literal["no_reference", "matches", "differs"]
    distance: float | None = None
    threshold: float | None = None
    n_genuine: int = 0
    modalities: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    target: str
    kind: Literal["adulteration", "cultured", "freshness", "identity"]
    status: Literal["no_model", "model", "research"]
    label: str
    confidence: float | None = None
    model: dict | None = Field(default=None, description="Model kind, training size and cross-validated accuracy")


class ScanResult(BaseModel):
    scan_id: str
    food: str
    mode: Literal["check", "reference"]
    status: Literal["ok", "rejected", "stored"]
    quality: Quality
    match: Match
    findings: list[Finding]
    report: dict
