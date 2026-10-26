"""Sift Lab API. One REST API for the public app, the researcher lab and enterprise callers."""

from __future__ import annotations

import logging
import os
from typing import Any, Literal

import cv2
import numpy as np
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import card, registry
from .agent import LabAgent
from .analysis import colorimetric, screenlight
from .config import get_settings
from .meta_client import MetaClient, MetaUnavailable
from .store import Store

logging.basicConfig(level=logging.INFO)
VERSION = "0.1.0"
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_AUDIO_BYTES = 8 * 1024 * 1024

settings = get_settings()
store = Store(settings.db_path)
client = MetaClient(settings)
agent = LabAgent(client)

app = FastAPI(title="Sift Lab API", version=VERSION,
              description="Run food-fraud screening assays from a phone camera or the Sift device.")
app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["*"],
                   allow_headers=["*"])

Tier = Literal["public", "research", "enterprise"]


def api_key(x_sift_key: str | None = Header(default=None)) -> str | None:
    if x_sift_key:
        if not store.use_key(x_sift_key):
            raise HTTPException(401, "Unknown API key.")
        return x_sift_key
    if settings.require_api_key:
        raise HTTPException(401, "This server requires an X-Sift-Key header.")
    return None


def _assay_or_404(assay_id: str) -> dict:
    try:
        return registry.get(assay_id)
    except registry.AssayNotFound:
        raise HTTPException(404, f"No assay called '{assay_id}'.")


def _runnable_or_409(assay: dict, method: str) -> None:
    if not registry.is_runnable(assay):
        raise HTTPException(409, f"'{assay['name']}' is planned, not runnable yet.")
    if assay["method"] != method:
        raise HTTPException(409, f"'{assay['name']}' uses the {assay['method']} method, not {method}.")


def _accuracy(assay: dict) -> dict:
    runs = store.validation_runs(assay["id"])
    if not runs:
        return {"n": 0, "summary": "Not measured yet: no runs with known answers."}
    numeric = [r for r in runs if r["result"].get("value") is not None]
    if numeric:
        err = [abs(r["result"]["value"] - r["truth"]) for r in numeric]
        return {"n": len(numeric), "mae": round(float(np.mean(err)), 3), "unit": assay["analysis"].get("unit"),
                "summary": f"Mean absolute error {np.mean(err):.2f} over {len(numeric)} known samples."}
    agree = [(r["result"]["verdict"] == "flag") == (r["truth"] > 0) for r in runs]
    return {"n": len(runs), "agreement": round(float(np.mean(agree)), 3),
            "summary": f"Agreed with the known answer in {sum(agree)} of {len(runs)} samples."}


def _summary(a: dict) -> dict:
    return {k: a.get(k) for k in ("id", "name", "food", "question", "status", "method", "instruments",
                                  "summary", "references")} | {"runnable": registry.is_runnable(a)}


# ------------------------------------------------------------------ meta
@app.get("/health")
def health() -> dict:
    return {"ok": True, "version": VERSION, "agent": "muse-spark" if client.online else "offline",
            "chat_model": settings.chat_model}


@app.get("/v1/assays")
def list_assays() -> list[dict]:
    return [_summary(a) | {"accuracy": _accuracy(a) if registry.is_runnable(a) else None}
            for a in registry.load_all().values()]


@app.get("/v1/assays/{assay_id}")
def get_assay(assay_id: str) -> dict:
    a = _assay_or_404(assay_id)
    out = dict(a) | {"runnable": registry.is_runnable(a)}
    if registry.is_runnable(a):
        out["accuracy"] = _accuracy(a)
        out["models"] = store.list_models(assay_id)
    return out


@app.get("/v1/card.svg")
def reference_card() -> Response:
    return Response(card.card_svg(), media_type="image/svg+xml",
                    headers={"Content-Disposition": 'inline; filename="sift-reference-card.svg"'})


# ------------------------------------------------------------------ runs
def _decode_image(raw: bytes) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(422, "The upload isn't a readable image.")
    h, w = img.shape[:2]
    scale = 2000 / max(h, w)
    if scale < 1:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return img


def _finish(assay: dict, result: dict, tier: str, device: str, instrument: str, features: Any,
            key: str | None, review: dict | None = None) -> dict:
    result["report"] = agent.write_report(assay, result, tier)
    if review is not None:
        result["capture_review"] = review
    run_id = store.save_run(assay["id"], tier, device, instrument, result["status"], result, features, key)
    return {"run_id": run_id, "assay_id": assay["id"], **result}


@app.post("/v1/runs/card")
async def run_card(assay_id: str = Form(...), image: UploadFile = File(...), device: str = Form("unknown"),
                   tier: Tier = Form("public"), instrument: str = Form("phone-camera"),
                   key: str | None = Depends(api_key)) -> dict:
    assay = _assay_or_404(assay_id)
    _runnable_or_409(assay, "colorimetric")
    raw = await image.read()
    if len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Image is larger than 12 MB.")
    img = _decode_image(raw)
    model = store.get_model(assay_id, device)
    sam_mask = None
    try:
        warped = card.detect_and_rectify(img)
    except card.CardNotFound as exc:
        result = {"status": "rejected", "quality": {"ok": False, "metrics": {}, "problems": [{
            "code": "card_not_found", "severity": "reject", "message": str(exc),
            "fix": "Fit the whole card in the frame so all four black corner squares show."}]}}
        return _finish(assay, result, tier, device, instrument, None, key)

    ok, jpeg = cv2.imencode(".jpg", warped, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if client.online:
        try:
            sam_mask = client.segment(jpeg.tobytes(), "the sample inside the black ring", warped.shape[:2])
        except MetaUnavailable as exc:
            logging.getLogger("sift").info("SAM unavailable, using card-window segmentation: %s", exc)
            sam_mask = None
    # analyze() re-detects on the original image; pass a mask in rectified-card coordinates.
    result = colorimetric.analyze(img, assay, model, sam_mask)
    review = agent.review_capture(assay, jpeg.tobytes()) if result["status"] == "ok" else None
    if review and not review.get("sample_visible", True):
        result["quality"]["problems"].append({"code": "agent_no_sample", "severity": "warn",
                                              "message": "The Lab Agent couldn't see a sample in the ring.",
                                              "fix": review.get("advice", "Retake the photo.")})
    return _finish(assay, result, tier, device, instrument, result.get("features"), key, review)


class ScreenlightRun(BaseModel):
    assay_id: str
    device: str = "unknown"
    tier: Tier = "public"
    instrument: str = "phone-screen"
    frames: dict[str, list[list[float]]] = Field(description="colour -> list of mean [r,g,b] in 0..1 per frame")


@app.post("/v1/runs/screenlight")
def run_screenlight(body: ScreenlightRun, key: str | None = Depends(api_key)) -> dict:
    assay = _assay_or_404(body.assay_id)
    _runnable_or_409(assay, "screenlight")
    model = store.get_model(body.assay_id, body.device)
    try:
        result = screenlight.analyze(body.frames, assay, model)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return _finish(assay, result, body.tier, body.device, body.instrument,
                   result.get("features", {}).get("vector"), key)


@app.get("/v1/runs")
def list_runs(assay_id: str | None = None, limit: int = 50) -> list[dict]:
    return store.list_runs(assay_id, min(limit, 200))


@app.get("/v1/runs/{run_id}")
def get_run(run_id: str) -> dict:
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(404, "No such run.")
    return run


class Truth(BaseModel):
    value: float = Field(description="The known answer for this sample (concentration, or 0/1 for absent/present)")


@app.post("/v1/runs/{run_id}/truth")
def set_truth(run_id: str, body: Truth) -> dict:
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(404, "No such run.")
    store.set_truth(run_id, body.value)
    return {"ok": True, "accuracy": _accuracy(registry.get(run["assay_id"]))}


# ------------------------------------------------------------------ calibration
class SampleFromRun(BaseModel):
    run_id: str
    known_value: float
    note: str = ""


@app.post("/v1/calibration/samples")
def add_sample(body: SampleFromRun) -> dict:
    run = store.get_run(body.run_id)
    if not run:
        raise HTTPException(404, "No such run.")
    if run["status"] not in ("ok", "needs_calibration") or run["features"] is None:
        raise HTTPException(409, "Only runs that passed the quality checks can be calibration samples.")
    assay = registry.get(run["assay_id"])
    feats = run["features"]
    if assay["method"] == "colorimetric":
        feats = feats[assay["analysis"]["feature"]]
    sid = store.add_sample(run["assay_id"], run["device"] or "unknown", body.known_value, feats, body.note)
    return {"sample_id": sid, "samples": len(store.samples(run["assay_id"], run["device"] or "unknown"))}


class TrainRequest(BaseModel):
    assay_id: str
    device: str


@app.post("/v1/calibration/train")
def train(body: TrainRequest) -> dict:
    assay = _assay_or_404(body.assay_id)
    samples = store.samples(body.assay_id, body.device)
    try:
        if assay["method"] == "screenlight":
            payload, metrics = screenlight.train(samples)
            kind = "pls"
        else:
            curve = colorimetric.fit_curve([(s["features"], s["known_value"]) for s in samples])
            payload, kind = curve, "curve"
            metrics = {"samples": curve["samples"], "levels": curve["levels"], "noise": curve["noise"],
                       "validation": "calibration points only; validate with known samples"}
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    store.save_model(body.assay_id, body.device, kind, payload, metrics)
    return {"ok": True, "kind": kind, "metrics": metrics}


@app.get("/v1/calibration/{assay_id}")
def calibration_state(assay_id: str, device: str) -> dict:
    _assay_or_404(assay_id)
    model = store.get_model(assay_id, device)
    return {"samples": store.samples(assay_id, device),
            "model": {k: model[k] for k in ("kind", "created", "metrics")} if model else None}


# ------------------------------------------------------------------ agent
class AgentTurn(BaseModel):
    assay_id: str
    step_id: str | None = None
    message: str
    history: list[dict] = []
    tier: Tier = "public"


@app.post("/v1/agent/turn")
def agent_turn(body: AgentTurn) -> dict:
    _assay_or_404(body.assay_id)
    return agent.turn(body.assay_id, body.step_id, body.history, body.message, body.tier)


@app.post("/v1/transcribe")
async def transcribe(audio: UploadFile = File(...)) -> dict:
    raw = await audio.read()
    if len(raw) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "Audio is larger than 8 MB.")
    if not client.online:
        raise HTTPException(503, "Voice needs the Meta Model API key on the server.")
    try:
        text = client.transcribe(raw, audio.filename or "voice.webm", audio.content_type or "audio/webm")
    except MetaUnavailable as exc:
        raise HTTPException(502, str(exc))
    return {"text": text}


# ------------------------------------------------------------------ keys
class KeyRequest(BaseModel):
    owner: str


@app.post("/v1/keys")
def create_key(body: KeyRequest, x_admin_token: str | None = Header(default=None)) -> dict:
    admin = os.environ.get("SIFT_ADMIN_TOKEN")
    if not admin or x_admin_token != admin:
        raise HTTPException(403, "Admin token required.")
    return {"key": store.create_key(body.owner), "owner": body.owner}
