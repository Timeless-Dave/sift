"""Thin client for Meta Model API (OpenAI-compatible, https://api.meta.ai/v1).

Chat and vision go through /chat/completions with OpenAI-style messages and tools.
Transcription goes through /audio/transcriptions. SAM 3.1's request shape should be checked
against dev.meta.ai/docs/models; the path is configurable and every caller has a fallback.

Without MODEL_API_KEY the client reports itself offline and callers use their deterministic
paths. Offline output is labelled as such in every response; nothing pretends to be a model.
"""

from __future__ import annotations

import base64
import json
import logging

import httpx
import numpy as np

from .config import Settings

log = logging.getLogger("sift.meta")


class MetaUnavailable(RuntimeError):
    pass


class MetaClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.s = settings
        self._http = httpx.Client(
            base_url=settings.meta_base_url,
            headers={"Authorization": f"Bearer {settings.meta_api_key}"},
            timeout=httpx.Timeout(45.0, connect=10.0),
            transport=transport,
        )

    @property
    def online(self) -> bool:
        return self.s.agent_online

    def _require(self) -> None:
        if not self.online:
            raise MetaUnavailable("MODEL_API_KEY is not set")

    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             tool_choice: str | dict | None = None, temperature: float = 0.2, max_tokens: int = 700) -> dict:
        self._require()
        body: dict = {"model": self.s.chat_model, "messages": messages,
                      "temperature": temperature, "max_tokens": max_tokens}
        if tools:
            body["tools"] = tools
            if tool_choice:
                body["tool_choice"] = tool_choice
        r = self._http.post("/chat/completions", json=body)
        if r.status_code >= 400:
            raise MetaUnavailable(f"Meta Model API {r.status_code}: {r.text[:300]}")
        return r.json()["choices"][0]["message"]

    def call_tool(self, messages: list[dict], tool: dict) -> dict:
        """Force one structured tool call and return its parsed arguments."""
        msg = self.chat(messages, tools=[tool],
                        tool_choice={"type": "function", "function": {"name": tool["function"]["name"]}})
        calls = msg.get("tool_calls") or []
        if not calls:
            raise MetaUnavailable("Model returned no tool call")
        return json.loads(calls[0]["function"]["arguments"])

    def transcribe(self, audio: bytes, filename: str, mime: str) -> str:
        self._require()
        r = self._http.post("/audio/transcriptions",
                            data={"model": self.s.transcribe_model},
                            files={"file": (filename, audio, mime)})
        if r.status_code >= 400:
            raise MetaUnavailable(f"Transcription {r.status_code}: {r.text[:300]}")
        return r.json().get("text", "").strip()

    def segment(self, image_jpeg: bytes, prompt: str, shape: tuple[int, int]) -> np.ndarray:
        """Ask SAM 3.1 for a mask of `prompt`. Returns a boolean mask of `shape` (h, w)."""
        self._require()
        body = {"model": self.s.sam_model, "image": _data_url(image_jpeg), "prompt": prompt}
        r = self._http.post(self.s.sam_path, json=body)
        if r.status_code >= 400:
            raise MetaUnavailable(f"SAM {r.status_code}: {r.text[:300]}")
        data = r.json()
        masks = data.get("masks") or data.get("data") or []
        if not masks:
            raise MetaUnavailable("SAM returned no mask")
        first = masks[0]
        encoded = first.get("mask") or first.get("png") or first.get("b64_json")
        if not encoded:
            raise MetaUnavailable("Unrecognised SAM mask format")
        import cv2  # local import keeps the client light for non-vision callers

        raw = base64.b64decode(encoded.split(",")[-1])
        mask = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
        if mask is None:
            raise MetaUnavailable("Could not decode SAM mask")
        mask = cv2.resize(mask, (shape[1], shape[0]), interpolation=cv2.INTER_NEAREST)
        return mask > 127


def _data_url(jpeg: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()


def image_part(jpeg: bytes) -> dict:
    return {"type": "image_url", "image_url": {"url": _data_url(jpeg)}}
