from fastapi import APIRouter, Depends
from fastapi.responses import Response

from ...domain import registry
from ...vision import card
from ..deps import Container, container

router = APIRouter(tags=["assays"])

PUBLIC_FIELDS = ("id", "name", "food", "question", "status", "method", "instruments", "summary", "references")


@router.get("/v1/assays", summary="List every test, runnable and planned")
def list_assays(c: Container = Depends(container)) -> list[dict]:
    return [{k: a.get(k) for k in PUBLIC_FIELDS} | {
        "runnable": registry.is_runnable(a),
        "accuracy": c.runs.accuracy(a) if registry.is_runnable(a) else None,
    } for a in registry.load_all().values()]


@router.get("/v1/assays/{assay_id}", summary="One test with its protocol, method, sources and accuracy")
def get_assay(assay_id: str, c: Container = Depends(container)) -> dict:
    a = registry.get(assay_id)
    out = dict(a) | {"runnable": registry.is_runnable(a)}
    if registry.is_runnable(a):
        out["accuracy"] = c.runs.accuracy(a)
        out["models"] = c.store.list_models(assay_id)
    return out


@router.get("/v1/card.svg", summary="Printable reference card (print at 100%)")
def reference_card() -> Response:
    return Response(card.card_svg(), media_type="image/svg+xml",
                    headers={"Content-Disposition": 'inline; filename="sift-reference-card.svg"',
                             "Cache-Control": "public, max-age=86400"})
