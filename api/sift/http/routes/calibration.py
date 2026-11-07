from fastapi import APIRouter, Depends, Path, Query

from ...data.store import PUBLIC
from ..deps import Container, Identity, container, identity, require_calibration_key
from ..schemas import SampleFromRun, TrainRequest, normalize_device

router = APIRouter(tags=["calibration"])


@router.post("/v1/calibration/samples", summary="Use a run with a known answer as a calibration sample")
def add_sample(body: SampleFromRun, who: Identity = Depends(require_calibration_key),
               c: Container = Depends(container)) -> dict:
    return {"samples": c.calibration.add_sample(body.run_id, body.known_value, body.note, viewer=who.key_prefix)}


@router.post("/v1/calibration/train", summary="Train this phone's model from its calibration samples")
def train(body: TrainRequest, who: Identity = Depends(require_calibration_key),
          c: Container = Depends(container)) -> dict:
    return {"ok": True, **c.calibration.train(body.assay_id, normalize_device(body.device), who.key_prefix or PUBLIC)}


@router.get("/v1/calibration/{assay_id}", summary="Calibration samples and model for one phone")
def state(assay_id: str = Path(min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$"),
          device: str = Query(min_length=1, max_length=80, pattern=r"^[\w .,()+\-/x]+$"),
          who: Identity = Depends(identity), c: Container = Depends(container)) -> dict:
    return c.calibration.state(assay_id, normalize_device(device), who.key_prefix or PUBLIC)
