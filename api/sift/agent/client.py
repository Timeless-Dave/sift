"""Thin client for Meta Model API (OpenAI-compatible, https://api.meta.ai/v1).

Chat and vision go through /chat/completions with OpenAI-style messages and tools.
Transcription goes through /asr/transcribe. SAM 3.1's endpoint and request shape should be checked
against dev.meta.ai/docs/models; the path is configurable and every caller has a fallback.

Without MODEL_API_KEY the client reports itself offline and callers use their deterministic
paths. Offline output is labelled as such in every response; nothing pretends to be a model.
"""

from __future__ import annotations

import base64
import json
import logging
import threading
import time

import httpx
import numpy as np

from ..core.config import Settings

log = logging.getLogger("sift.meta")


class MetaUnavailable(RuntimeError):
    pass


class CircuitBreaker:
    """After `threshold` consecutive failures, fail fast for `cooldown` seconds so a Meta
    outage doesn't make every request wait on timeouts."""

    def __init__(self, threshold: int = 3, cooldown: float = 60.0):
        self.threshold, self.cooldown = threshold, cooldown
        self.failures, self.opened_at = 0, 0.0
        self._lock = threading.Lock()

    def allow(self) -> bool:
        with self._lock:
            if self.failures < self.threshold:
                return True
            if time.monotonic() - self.opened_at >= self.cooldown:
                self.failures = self.threshold - 1  # half-open: one trial request
                return True
            return False

    def record(self, ok: bool) -> None:
        with self._lock:
            if ok:
                self.failures = 0
            else:
                self.failures += 1
                if self.failures >= self.threshold:
                    self.opened_at = time.monotonic()


RETRY_STATUS = {429, 500, 502, 503, 504}


class MetaClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None,
                 retries: int = 2, backoff: float = 0.6):
        self.s = settings
        self.breaker = CircuitBreaker()
        self.retries, self.backoff = retries, backoff
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
        if not self.breaker.allow():
            raise MetaUnavailable("Meta Model API is failing; paused for a minute")

    def _post(self, path: str, **kwargs) -> httpx.Response:
        """POST with retries on rate limits, server errors and network faults."""
        self._require()
        last = ""
        for attempt in range(self.retries + 1):
            try:
                r = self._http.post(path, **kwargs)
            except httpx.HTTPError as exc:
                last = f"network error: {type(exc).__name__}"
            else:
                if r.status_code < 400:
                    self.breaker.record(True)
                    return r
                last = f"{r.status_code}: {r.text[:200]}"
                if r.status_code not in RETRY_STATUS:
                    self.breaker.record(False)
                    raise MetaUnavailable(f"Meta Model API {last}")
            if attempt < self.retries:
                time.sleep(self.backoff * (2 ** attempt))
        self.breaker.record(False)
        raise MetaUnavailable(f"Meta Model API {last}")

    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             tool_choice: str | dict | None = None, temperature: float = 0.2, max_tokens: int = 700) -> dict:
        body: dict = {"model": self.s.chat_model, "messages": messages,
                      "temperature": temperature, "max_tokens": max_tokens}
        if tools:
            body["tools"] = tools
            if tool_choice:
                body["tool_choice"] = tool_choice
        r = self._post("/chat/completions", json=body)
        try:
            return r.json()["choices"][0]["message"]
        except (KeyError, IndexError, ValueError) as exc:
            raise MetaUnavailable("Unexpected chat response shape") from exc

    def call_tool(self, messages: list[dict], tool: dict) -> dict:
        """Force one structured tool call and return its parsed arguments."""
        msg = self.chat(messages, tools=[tool],
                        tool_choice={"type": "function", "function": {"name": tool["function"]["name"]}})
        calls = msg.get("tool_calls") or []
        if not calls:
            raise MetaUnavailable("Model returned no tool call")
        try:
            args = json.loads(calls[0]["function"]["arguments"])
        except (KeyError, json.JSONDecodeError) as exc:
            raise MetaUnavailable("Tool call arguments were not valid JSON") from exc
        if not isinstance(args, dict):
            raise MetaUnavailable("Tool call arguments were not an object")
        return args

    def transcribe(self, audio: bytes, filename: str, mime: str) -> str:
        r = self._post(self.s.transcribe_path,
                       data={"model": self.s.transcribe_model},
                       files={"file": (filename, audio, mime)})
        data = r.json()
        text = data.get("text") or data.get("transcript") or ""
        if not text and isinstance(data.get("segments"), list):
            text = " ".join(str(seg.get("text", "")) for seg in data["segments"] if isinstance(seg, dict))
        return str(text).strip()

    def segment(self, image_jpeg: bytes, prompt: str, shape: tuple[int, int]) -> np.ndarray:
        """Ask SAM 3.1 for a mask of `prompt`. Returns a boolean mask of `shape` (h, w)."""
        body = {"model": self.s.sam_model, "image": _data_url(image_jpeg), "prompt": prompt}
        data = self._post(self.s.sam_path, json=body).json()
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
