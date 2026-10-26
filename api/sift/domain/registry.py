"""Assay registry: every test Sift can run is one YAML entry in sift/assays/."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from ..core.errors import Conflict, NotFound

ASSAY_DIR = Path(__file__).parent / "assays"

RUNNABLE = {"experimental", "validated"}


class AssayNotFound(NotFound):
    pass


@lru_cache(maxsize=1)
def load_all() -> dict[str, dict[str, Any]]:
    assays: dict[str, dict[str, Any]] = {}
    for path in sorted(ASSAY_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        entries = data if isinstance(data, list) else [data]
        for entry in entries:
            _validate(entry, path)
            if entry["id"] in assays:
                raise ValueError(f"Duplicate assay id {entry['id']} in {path.name}")
            assays[entry["id"]] = entry
    return assays


def _validate(entry: dict[str, Any], path: Path) -> None:
    required = ["id", "name", "food", "status", "method", "references"]
    missing = [k for k in required if k not in entry]
    if missing:
        raise ValueError(f"{path.name}: assay {entry.get('id')} missing {missing}")
    if not entry["references"]:
        raise ValueError(f"{path.name}: assay {entry['id']} must cite at least one source")
    if entry["status"] in RUNNABLE:
        for key in ("protocol", "analysis"):
            if key not in entry:
                raise ValueError(f"{path.name}: runnable assay {entry['id']} needs '{key}'")
        captures = [s for s in entry["protocol"] if s.get("capture")]
        if len(captures) != 1:
            raise ValueError(f"{path.name}: assay {entry['id']} needs exactly one capture step")


def get(assay_id: str) -> dict[str, Any]:
    try:
        return load_all()[assay_id]
    except KeyError as exc:
        raise AssayNotFound(f"No assay called '{assay_id}'.") from exc


def is_runnable(assay: dict[str, Any]) -> bool:
    return assay["status"] in RUNNABLE


def require_runnable(assay: dict[str, Any], method: str) -> None:
    if not is_runnable(assay):
        raise Conflict(f"'{assay['name']}' is planned, not runnable yet.")
    if assay["method"] != method:
        raise Conflict(f"'{assay['name']}' uses the {assay['method']} method, not {method}.")


def step_ids(assay: dict[str, Any]) -> set[str]:
    return {s["id"] for s in assay.get("protocol", [])}


def capture_step(assay: dict[str, Any]) -> dict[str, Any]:
    return next(s for s in assay["protocol"] if s.get("capture"))
