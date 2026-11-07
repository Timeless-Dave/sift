from fastapi import APIRouter, Depends, Path, Query

from ...core.errors import NotFound
from ...data.store import PUBLIC
from ...domain import foods
from ...scan.schemas import ScanRequest, ScanResult
from ...services.runs import Caller
from ..deps import Container, Identity, container, identity, require_calibration_key, viewer
from ..schemas import normalize_device

router = APIRouter(tags=["scans"])


@router.post("/v1/scans", summary="Check a food against its reference scans, or store a reference scan")
def post_scan(body: ScanRequest, who: Identity = Depends(identity),
              c: Container = Depends(container)) -> ScanResult:
    if body.mode == "reference":
        require_calibration_key(who, c)
    return c.scans.run(body, Caller("public", normalize_device(body.device), "phone", who.key_prefix))


@router.get("/v1/scans", summary="Recent scans")
def list_scans(food: str | None = Query(default=None, min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$"),
               limit: int = 50, who: Identity = Depends(identity),
               c: Container = Depends(container)) -> list[dict]:
    return c.store.list_scans(food, max(1, min(limit, 200)), viewer=who.key_prefix)


@router.get("/v1/scans/{scan_id}", summary="One scan")
def get_scan(scan_id: str = Path(min_length=6, max_length=32, pattern=r"^[a-f0-9]+$"),
             who: Identity = Depends(identity), c: Container = Depends(container)) -> dict:
    scan = c.store.get_scan(scan_id, viewer=who.key_prefix)
    if not scan:
        raise NotFound("No such scan.")
    return scan


def _target_entry(target: dict, counts: dict, full: bool) -> dict:
    entry = {"id": target["id"], "kind": target["kind"], "question": target["question"], "status": target["status"],
             "reference_scans": sum(counts["by_target"].get(target["id"], {}).values())}
    if full:
        entry |= {"signals": target["signals"], "likely_causes": target["likely_causes"],
                  "references": target["references"]}
    return entry


@router.get("/v1/foods", summary="List every food with a scan profile")
def list_foods(who: str | None = Depends(viewer), c: Container = Depends(container)) -> list[dict]:
    owner = who or PUBLIC
    out = []
    for food in foods.load_all().values():
        counts = c.store.reference_counts(food["id"], owner)
        out.append({"id": food["id"], "name": food["name"], "category": food["category"], "aliases": food["aliases"],
                    "scan": food["scan"], "targets": [_target_entry(t, counts, full=False) for t in food["targets"]],
                    "counts": counts})
    return out


@router.get("/v1/foods/{food_id}", summary="One food profile with its reference counts")
def get_food(food_id: str = Path(min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$"),
             who: str | None = Depends(viewer), c: Container = Depends(container)) -> dict:
    food = foods.get(food_id)
    counts = c.store.reference_counts(food["id"], who or PUBLIC)
    return {**food, "targets": [_target_entry(t, counts, full=True) for t in food["targets"]], "counts": counts}
