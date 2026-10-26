"""Request bodies. Field limits here are the first line of input validation."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Tier = Literal["public", "research", "enterprise"]
DeviceLabel = Field(default="unknown", min_length=1, max_length=80, pattern=r"^[\w .,()+\-/x]+$")
AssayId = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")


class ScreenlightRun(BaseModel):
    assay_id: str = AssayId
    device: str = DeviceLabel
    tier: Tier = "public"
    instrument: Literal["phone-screen", "sift-device"] = "phone-screen"
    frames: dict[str, list[list[float]]] = Field(
        description="colour name -> list of mean [r, g, b] in 0..1, one per captured frame")


class Truth(BaseModel):
    value: float = Field(ge=0, le=1_000_000,
                         description="Known answer: a concentration, or 0/1 for absent/present")


class SampleFromRun(BaseModel):
    run_id: str = Field(min_length=6, max_length=32, pattern=r"^[a-f0-9]+$")
    known_value: float = Field(ge=0, le=1_000_000)
    note: str = Field(default="", max_length=200)


class TrainRequest(BaseModel):
    assay_id: str = AssayId
    device: str = DeviceLabel


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=2000)


class AgentTurn(BaseModel):
    assay_id: str = AssayId
    step_id: str | None = Field(default=None, max_length=64)
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=40)
    tier: Tier = "public"


class KeyRequest(BaseModel):
    owner: str = Field(min_length=2, max_length=120)
