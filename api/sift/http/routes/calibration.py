from fastapi import APIRouter, Depends, Query

from ..deps import Container, Identity, container, identity
from ..schemas import SampleFromRun, TrainRequest

router = APIRouter(tags=["calibration"])


@router.post("/v1/calibration/samples", summary="Use a run with a known answer as a calibration sample")
def add_sample(body: SampleFromRun, who: Identity = Depends(identity), c: Container = Depends(container)) -> dict:
    return {"samples": c.calibration.add_sample(body.run_id, body.known_value, body.note, viewer=who.key_prefix)}


@router.post("/v1/calibration/train", summary="Train this phone's model from its calibration samples")
def train(body: TrainRequest, _: Identity = Depends(identity), c: Container = Depends(container)) -> dict:
    return {"ok": True, **c.calibration.train(body.assay_id, body.device)}


@router.get("/v1/calibration/{assay_id}", summary="Calibration samples and model for one phone")
def state(assay_id: str, device: str = Query(min_length=1, max_length=80),
          c: Container = Depends(container)) -> dict:
    return c.calibration.state(assay_id, device)
