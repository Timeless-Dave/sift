"""Thin client for Meta Model API (OpenAI-compatible, https://api.meta.ai/v1).

Chat and vision go through /chat/completions with OpenAI-style messages and tools.
Transcription goes through /asr/transcribe. SAM 3.1 segments through /responses with an
input_text prompt plus an input_image part; geometry comes back as special-token text in
the output_text lane (see sift.agent.sam).

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
from . import sam

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

    def segment(self, image_jpeg: bytes, prompt: str, shape: tuple[int, int]) -> list[np.ndarray]:
        """Ask SAM 3.1 for every match of `prompt`. Returns one boolean mask of `shape` (h, w) per match.

        SAM wants a short noun phrase ("circle"), not a sentence; longer prompts often match nothing.
        Each mask raster covers only its box, so it is placed at the box inside a full-frame mask.
        Any failure, including zero matches, raises MetaUnavailable so callers fall back to
        card-window segmentation.
        """
        body = {"model": self.s.sam_model,
                "input": [{"type": "message", "role": "user", "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": _data_url(image_jpeg)}]}],
                "metadata": {"mask_encoding": "one_bit"},
                "stream": False}
        try:
            data = self._post(self.s.sam_path, json=body).json()
        except ValueError as exc:
            raise MetaUnavailable("SAM response was not JSON") from exc
        try:
            records = sam.parse_output_text(_responses_text(data))
            return [_place(rec, sam.decode_mask(rec.mask), shape) for rec in records]
        except ValueError as exc:
            raise MetaUnavailable(f"Unexpected SAM response shape: {exc}") from exc


def _place(rec: sam.SamRecord, raster: bytes, shape: tuple[int, int]) -> np.ndarray:
    """Put a box-sized mask raster into a frame-sized mask, then scale it to `shape` (h, w)."""
    import cv2  # local import keeps the client light for non-vision callers

    x1, y1, x2, y2, fw, fh = rec.box
    local = np.frombuffer(raster, dtype=np.uint8).reshape(rec.mask.height, rec.mask.width)
    bw, bh = x2 - x1 + 1, y2 - y1 + 1
    if local.shape != (bh, bw):
        local = cv2.resize(local, (bw, bh), interpolation=cv2.INTER_NEAREST)
    frame = np.zeros((fh, fw), np.uint8)
    frame[y1:y2 + 1, x1:x2 + 1] = local
    if (fh, fw) != tuple(shape):
        frame = cv2.resize(frame, (shape[1], shape[0]), interpolation=cv2.INTER_NEAREST)
    return frame > 0


def _responses_text(data: object) -> str:
    """Pull the output_text lane out of a non-streaming Responses API reply."""
    if not isinstance(data, dict):
        raise MetaUnavailable("Unexpected SAM response shape")
    status = data.get("status")
    if status is not None and status != "completed":
        raise MetaUnavailable(f"SAM response was {status}")
    output = data.get("output")
    if not isinstance(output, list):
        raise MetaUnavailable("Unexpected SAM response shape")
    saw_text = False
    for item in output:
        content = item.get("content") if isinstance(item, dict) else None
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "output_text":
                continue
            saw_text = True
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                return text
    if saw_text:
        raise MetaUnavailable("SAM found no match")  # zero matches: a valid empty lane
    raise MetaUnavailable("Unexpected SAM response shape")


def _data_url(jpeg: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()


def image_part(jpeg: bytes) -> dict:
    return {"type": "image_url", "image_url": {"url": _data_url(jpeg)}}
