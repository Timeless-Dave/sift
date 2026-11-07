from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from ...data.store import PUBLIC
from ...domain import registry
from ...vision import card
from ..deps import Container, client_ip, container, viewer

router = APIRouter(tags=["assays"])

PUBLIC_FIELDS = ("id", "name", "food", "question", "status", "method", "instruments", "summary", "references")


@router.get("/v1/assays", summary="List every test, runnable and planned")
def list_assays(who: str | None = Depends(viewer), c: Container = Depends(container)) -> list[dict]:
    return [{k: a.get(k) for k in PUBLIC_FIELDS} | {
        "runnable": registry.is_runnable(a),
        "accuracy": c.runs.accuracy(a, who) if registry.is_runnable(a) else None,
    } for a in registry.load_all().values()]


@router.get("/v1/assays/{assay_id}", summary="One test with its protocol, method, sources and accuracy")
def get_assay(assay_id: str, who: str | None = Depends(viewer), c: Container = Depends(container)) -> dict:
    a = registry.get(assay_id)
    out = dict(a) | {"runnable": registry.is_runnable(a)}
    if registry.is_runnable(a):
        out["accuracy"] = c.runs.accuracy(a, who)
        out["models"] = c.store.list_models(assay_id, who or PUBLIC)
    return out


@router.get("/v1/card.svg", summary="Printable reference card (print at 100%)")
def reference_card(request: Request, c: Container = Depends(container)) -> Response:
    c.limiter.hit("api", client_ip(request, c), c.settings.limits.rate_public)
    return Response(card.card_svg(), media_type="image/svg+xml",
                    headers={"Content-Disposition": 'inline; filename="sift-reference-card.svg"',
                             "Cache-Control": "public, max-age=86400"})
