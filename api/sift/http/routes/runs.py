from fastapi import APIRouter, Depends, File, Form, UploadFile
from starlette.concurrency import run_in_threadpool

from ...core.errors import NotFound, TooLarge
from ...services.runs import Caller
from ..deps import Container, Identity, container, identity, require_tier
from ..schemas import ScreenlightRun, Tier, Truth

router = APIRouter(tags=["runs"])


async def _read_capped(upload: UploadFile, limit: int) -> bytes:
    raw = await upload.read(limit + 1)
    if len(raw) > limit:
        raise TooLarge(f"Uploads must be under {limit // (1024 * 1024)} MB.")
    return raw


@router.post("/v1/runs/card", summary="Run a colour test from a photo of the reference card")
async def run_card(assay_id: str = Form(..., min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$"),
                   image: UploadFile = File(...),
                   device: str = Form("unknown", min_length=1, max_length=80, pattern=r"^[\w .,()+\-/x]+$"),
                   tier: Tier = Form("public"),
                   instrument: str = Form("phone-camera", pattern=r"^(phone-camera|sift-device)$"),
                   who: Identity = Depends(identity), c: Container = Depends(container)) -> dict:
    require_tier(tier, who)
    raw = await _read_capped(image, c.settings.limits.max_image_bytes)
    # Image work and model calls block; keep them off the event loop.
    return await run_in_threadpool(c.runs.run_card, assay_id, raw,
                                   Caller(tier, device.strip() or "unknown", instrument, who.key_prefix))


@router.post("/v1/runs/screenlight", summary="Run a screen-light scan from per-colour camera means")
def run_screenlight(body: ScreenlightRun, who: Identity = Depends(identity),
                    c: Container = Depends(container)) -> dict:
    require_tier(body.tier, who)
    return c.runs.run_screenlight(body.assay_id, body.frames,
                                  Caller(body.tier, body.device, body.instrument, who.key_prefix))


@router.get("/v1/runs", summary="Recent runs")
def list_runs(assay_id: str | None = None, limit: int = 50, who: Identity = Depends(identity),
              c: Container = Depends(container)) -> list[dict]:
    return c.store.list_runs(assay_id, max(1, min(limit, 200)), viewer=who.key_prefix)


@router.get("/v1/runs/{run_id}", summary="One run")
def get_run(run_id: str, who: Identity = Depends(identity), c: Container = Depends(container)) -> dict:
    run = c.store.get_run(run_id, viewer=who.key_prefix)
    if not run:
        raise NotFound("No such run.")
    return run


@router.post("/v1/runs/{run_id}/truth", summary="Record the known answer, making this a validation run")
def set_truth(run_id: str, body: Truth, who: Identity = Depends(identity),
              c: Container = Depends(container)) -> dict:
    return {"ok": True, "accuracy": c.runs.set_truth(run_id, body.value, viewer=who.key_prefix)}

