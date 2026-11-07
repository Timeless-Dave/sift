"""Run orchestration: validate input, measure, ask the agent, store. HTTP-agnostic."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from ..agent.client import MetaClient, MetaUnavailable
from ..agent.lab_agent import LabAgent
from ..core.config import Settings
from ..core.errors import Conflict, Forbidden, InvalidInput, NotFound, TooLarge
from ..core.security import check_pixels, sniff_image
from ..data.store import PUBLIC, Store
from ..domain import registry
from ..vision import card, colorimetric, screenlight

log = logging.getLogger("sift.runs")
MAX_EDGE = 2000
MAX_SAMPLES = 500


@dataclass
class Caller:
    tier: str
    device: str
    instrument: str
    key_prefix: str | None = None

    @property
    def owner(self) -> str:
        return self.key_prefix or PUBLIC


def _decode(raw: bytes, limit: int) -> np.ndarray:
    if len(raw) > limit:
        raise TooLarge(f"Images must be under {limit // (1024 * 1024)} MB.")
    sniff_image(raw)
    check_pixels(raw)
    try:
        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    except cv2.error as exc:  # OPENCV_IO_MAX_IMAGE_PIXELS (set in sift/__init__.py) refused it
        raise TooLarge("The photo has too many pixels. Use a photo under 50 megapixels.") from exc
    if img is None:
        raise InvalidInput("The upload isn't a readable image.")
    h, w = img.shape[:2]
    if min(h, w) < 480:
        raise InvalidInput("The photo is too small. Use at least 480 pixels on the short side.")
    scale = MAX_EDGE / max(h, w)
    if scale < 1:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return img


def validate_frames(frames: dict[str, list[list[float]]], assay: dict, s: Settings) -> None:
    seq = assay["analysis"]["sequence"]
    if len(frames) > s.limits.max_colours:
        raise InvalidInput("Too many colours in the scan.")
    unknown = set(frames) - set(seq)
    if unknown:
        raise InvalidInput(f"Unknown colours for this test: {sorted(unknown)[:5]}.")
    missing = [c for c in seq if c not in frames]
    if missing:
        raise InvalidInput(f"The scan is missing these colours: {missing[:5]}. Run it again.")
    for colour, rows in frames.items():
        if not 1 <= len(rows) <= s.limits.max_frames_per_colour:
            raise InvalidInput(f"Colour '{colour}' needs 1 to {s.limits.max_frames_per_colour} frames.")
        for rgb in rows:
            if len(rgb) != 3 or not all(isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v <= 1
                                        for v in rgb):
                raise InvalidInput("Each frame must be three numbers between 0 and 1.")


class RunService:
    def __init__(self, settings: Settings, store: Store, client: MetaClient, agent: LabAgent):
        self.s, self.store, self.client, self.agent = settings, store, client, agent

    def _finish(self, assay: dict, result: dict, who: Caller, features: Any, review: dict | None = None) -> dict:
        result["report"] = self.agent.write_report(assay, result, who.tier)
        if review is not None:
            result["capture_review"] = review
        run_id = self.store.save_run(assay["id"], who.tier, who.device, who.instrument, result["status"],
                                     result, features, who.key_prefix)
        log.info("run", extra={"fields": {"run": run_id, "assay": assay["id"], "status": result["status"],
                                          "verdict": result.get("verdict"), "agent": result["report"]["agent"]}})
        return {"run_id": run_id, "assay_id": assay["id"], **result}

    def run_card(self, assay_id: str, raw: bytes, who: Caller) -> dict:
        assay = registry.get(assay_id)
        registry.require_runnable(assay, "colorimetric")
        img = _decode(raw, self.s.limits.max_image_bytes)
        model = self.store.get_model(assay_id, who.device, who.owner)

        sam_masks, jpeg = None, None
        try:
            warped = card.detect_and_rectify(img)
            ok, enc = cv2.imencode(".jpg", warped, [cv2.IMWRITE_JPEG_QUALITY, 85])
            jpeg = enc.tobytes() if ok else None
        except card.CardNotFound:
            warped = None
        if jpeg and self.client.online:
            try:
                prompt = assay["analysis"].get("sam_prompt", "circle")
                sam_masks = self.client.segment(jpeg, prompt, warped.shape[:2])
            except MetaUnavailable as exc:
                log.info("SAM unavailable, using card-window segmentation", extra={"fields": {"why": str(exc)[:120]}})

        result = colorimetric.analyze(img, assay, model, sam_masks)
        review = self.agent.review_capture(assay, jpeg) if jpeg and result["status"] == "ok" else None
        if review and not review["sample_visible"]:
            result["quality"]["problems"].append({
                "code": "agent_no_sample", "severity": "warn",
                "message": "The Lab Agent couldn't see a sample in the ring.",
                "fix": review["advice"] or "Retake the photo with the sample in the middle of the ring."})
        return self._finish(assay, result, who, result.get("features"), review)

    def run_screenlight(self, assay_id: str, frames: dict, who: Caller) -> dict:
        assay = registry.get(assay_id)
        registry.require_runnable(assay, "screenlight")
        validate_frames(frames, assay, self.s)
        model = self.store.get_model(assay_id, who.device, who.owner)
        result = screenlight.analyze(frames, assay, model)
        return self._finish(assay, result, who, result.get("features", {}).get("vector"))

    # Accuracy -------------------------------------------------------------------------------
    def accuracy(self, assay: dict, viewer: str | None = None) -> dict:
        """Accuracy from validation runs with known answers, overall and per phone. Public callers
        see public runs only; a keyed caller sees its own runs only."""
        runs = self.store.validation_runs(assay["id"], viewer)
        out = _score(runs, assay)
        by_device: dict[str, list[dict]] = {}
        for r in runs:
            by_device.setdefault(r["device"] or "unknown", []).append(r)
        out["by_device"] = {d: _score(rs, assay) for d, rs in sorted(by_device.items())}
        return out

    def set_truth(self, run_id: str, value: float, viewer: str | None = None) -> dict:
        run = self.store.get_run(run_id, viewer=viewer)
        if not run:
            raise NotFound("No such run.")
        if run["status"] != "ok":
            raise Conflict("Only runs with a result can be validation runs.")
        if self.store.is_calibration_run(run_id):
            raise Conflict("This run is a calibration sample. Validate with a different sample.")
        if viewer is not None and self.store.run_owner(run_id) != viewer:
            # Otherwise a key could shift the public accuracy figure without seeing it move.
            raise Forbidden("An API key can record known answers only on runs made with that key.")
        self.store.set_truth(run_id, value)
        return self.accuracy(registry.get(run["assay_id"]), viewer)


def _score(runs: list[dict], assay: dict) -> dict:
    if not runs:
        return {"n": 0, "summary": "Not measured yet: no runs with known answers."}
    numeric = [r for r in runs if r["result"].get("value") is not None]
    if numeric:
        mae = float(np.mean([abs(r["result"]["value"] - r["truth"]) for r in numeric]))
        return {"n": len(numeric), "mae": round(mae, 3), "unit": assay["analysis"].get("unit"),
                "summary": f"Mean absolute error {mae:.2f} over {len(numeric)} known samples."}
    agree = [(r["result"]["verdict"] == "flag") == (r["truth"] > 0) for r in runs]
    return {"n": len(runs), "agreement": round(float(np.mean(agree)), 3),
            "summary": f"Agreed with the known answer in {sum(agree)} of {len(runs)} samples."}


class CalibrationService:
    def __init__(self, store: Store):
        self.store = store

    def add_sample(self, run_id: str, known: float, note: str, viewer: str | None = None) -> int:
        """Samples go to the run's owner: a keyed run can only be seen, and so only added, by its key."""
        run = self.store.get_run(run_id, viewer=viewer)
        if not run:
            raise NotFound("No such run.")
        if run["status"] not in ("ok", "needs_calibration") or run["features"] is None:
            raise Conflict("Only runs that passed the quality checks can be calibration samples.")
        if run["truth"] is not None:
            raise Conflict("This run is a validation run. Use a different sample for calibration.")
        if self.store.is_calibration_run(run_id):
            raise Conflict("This run is already a calibration sample.")
        assay = registry.get(run["assay_id"])
        feats = run["features"]
        if assay["method"] == "colorimetric":
            feats = feats[assay["analysis"]["feature"]]
        device = run["device"] or "unknown"
        owner = viewer or PUBLIC
        if self.store.count_samples(run["assay_id"], device, owner) >= MAX_SAMPLES:
            raise Conflict(f"This phone already has {MAX_SAMPLES} calibration samples for this test. "
                           "Train a model with the samples you have.")
        self.store.add_sample(run["assay_id"], device, known, feats, note[:200], owner=owner, run_id=run_id)
        return len(self.store.samples(run["assay_id"], device, owner))

    def train(self, assay_id: str, device: str, owner: str = PUBLIC) -> dict:
        assay = registry.get(assay_id)
        if not registry.is_runnable(assay):
            raise Conflict(f"'{assay['name']}' isn't runnable yet.")
        samples = self.store.samples(assay_id, device, owner)
        try:
            if assay["method"] == "screenlight":
                payload, metrics = screenlight.train(samples)
                kind = "pls"
            else:
                curve = colorimetric.fit_curve([(s["features"], s["known_value"]) for s in samples])
                payload, kind = curve, "curve"
                metrics = {"samples": curve["samples"], "levels": curve["levels"], "noise": curve["noise"],
                           "validation": "calibration points only; validate with separate known samples"}
        except ValueError as exc:
            raise InvalidInput(str(exc)) from exc
        self.store.save_model(assay_id, device, kind, payload, metrics, owner)
        return {"kind": kind, "metrics": metrics}

    def state(self, assay_id: str, device: str, owner: str = PUBLIC) -> dict:
        registry.get(assay_id)
        model = self.store.get_model(assay_id, device, owner)
        return {"samples": [{"known_value": s["known_value"], "created": s["created"]}
                            for s in self.store.samples(assay_id, device, owner)],
                "model": {k: model[k] for k in ("kind", "created", "metrics")} if model else None}
