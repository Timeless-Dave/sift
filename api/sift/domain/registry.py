"""Assay registry: every test Sift can run is one YAML entry in sift/assays/."""

from __future__ import annotations

import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from ..core.errors import Conflict, NotFound

ASSAY_DIR = Path(__file__).parent / "assays"

RUNNABLE = {"experimental", "validated"}
FEATURES = {"L", "a", "b", "chroma", "hue", "blueness", "redness", "darkness", "spread", "pixels"}
VERDICTS = {"pass", "caution", "flag"}
_CLAUSE = re.compile(r"^\s*([a-zA-Z_]+)\s*(<=|>=|<|>)\s*(-?\d+(?:\.\d+)?)\s*$")


class AssayNotFound(NotFound):
    pass


@lru_cache(maxsize=1)
def load_all() -> dict[str, dict[str, Any]]:
    assays: dict[str, dict[str, Any]] = {}
    for path in sorted(ASSAY_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text())
        except yaml.YAMLError as exc:
            raise ValueError(f"{path.name}: invalid YAML: {exc}. Fix the file.") from exc
        if data is None:
            continue
        entries = data if isinstance(data, list) else [data]
        for entry in entries:
            if entry is None:
                continue
            if not isinstance(entry, dict):
                raise ValueError(f"{path.name}: each assay must be a mapping, got {type(entry).__name__}. "
                                 "Fix the file.")
            _validate(entry, path)
            if entry["id"] in assays:
                raise ValueError(f"Duplicate assay id {entry['id']} in {path.name}")
            assays[entry["id"]] = entry
    return assays


def _validate(entry: dict[str, Any], path: Path) -> None:
    required = ["id", "name", "food", "status", "method", "references"]
    missing = [k for k in required if k not in entry]
    if missing:
        raise ValueError(f"{path.name}: assay {entry.get('id', '?')} missing {missing}. Add them.")
    refs = entry["references"]
    if not isinstance(refs, list) or not refs:
        raise ValueError(f"{path.name}: assay {entry['id']} must cite at least one source. Add a references list.")
    if entry["status"] in RUNNABLE:
        for key in ("protocol", "analysis"):
            if key not in entry:
                raise ValueError(f"{path.name}: runnable assay {entry['id']} needs '{key}'. Add it.")
        protocol = entry["protocol"]
        if not isinstance(protocol, list) or not protocol:
            raise ValueError(f"{path.name}: assay {entry['id']} needs a protocol list. Add protocol steps.")
        for step in protocol:
            if not isinstance(step, dict) or not step.get("id"):
                raise ValueError(f"{path.name}: assay {entry['id']} has a protocol step without an id. "
                                 "Give each step an id.")
        captures = [s for s in protocol if s.get("capture")]
        if len(captures) != 1:
            raise ValueError(f"{path.name}: assay {entry['id']} needs exactly one capture step")
        analysis = entry["analysis"]
        if not isinstance(analysis, dict):
            raise ValueError(f"{path.name}: assay {entry['id']} analysis must be a mapping. Fix analysis.")
        method = entry["method"]
        if method == "colorimetric":
            _validate_colorimetric(entry, path)
        elif method == "screenlight":
            _validate_screenlight(entry, path)
        else:
            raise ValueError(f"{path.name}: runnable assay {entry['id']} uses unknown method '{method}'. "
                             "Use colorimetric or screenlight.")


def _validate_bands(entry: dict[str, Any], path: Path) -> None:
    bands = entry["analysis"].get("bands")
    aid = entry["id"]
    if not isinstance(bands, list) or not bands:
        raise ValueError(f"{path.name}: assay {aid} analysis.bands must be a non-empty list. Add bands.")
    prev: float | None = None
    for band in bands:
        if not isinstance(band, dict):
            raise ValueError(f"{path.name}: assay {aid} has a band that is not a mapping. "
                             "Give each band max, label and verdict.")
        for key in ("max", "label", "verdict"):
            if key not in band:
                raise ValueError(f"{path.name}: assay {aid} has a band missing '{key}'. Add it.")
        mx = band["max"]
        if not isinstance(mx, (int, float)) or isinstance(mx, bool) or not math.isfinite(float(mx)):
            raise ValueError(f"{path.name}: assay {aid} has a band max that is not a number. Fix the bands.")
        if not isinstance(band["label"], str) or not band["label"].strip():
            raise ValueError(f"{path.name}: assay {aid} has a band without a label. Add labels.")
        if band["verdict"] not in VERDICTS:
            raise ValueError(f"{path.name}: assay {aid} has band verdict {band['verdict']!r}. "
                             f"Use one of {sorted(VERDICTS)}.")
        if prev is not None and not float(mx) > prev:
            raise ValueError(f"{path.name}: assay {aid} bands must be sorted by increasing max. Sort them.")
        prev = float(mx)


def _validate_colorimetric(entry: dict[str, Any], path: Path) -> None:
    spec = entry["analysis"]
    aid = entry["id"]
    for key in ("feature", "bands", "qualitative", "unit"):
        if key not in spec:
            raise ValueError(f"{path.name}: assay {aid} analysis needs '{key}'. Add it.")
    if spec["feature"] not in FEATURES:
        raise ValueError(f"{path.name}: assay {aid} uses unknown feature {spec['feature']!r}. "
                         f"Use one of {sorted(FEATURES)}.")
    if not isinstance(spec["unit"], str) or not spec["unit"].strip():
        raise ValueError(f"{path.name}: assay {aid} analysis.unit must be a non-empty string. Add a unit.")
    qual = spec["qualitative"]
    if not isinstance(qual, dict):
        raise ValueError(f"{path.name}: assay {aid} analysis.qualitative must be a mapping. Fix it.")
    for key in ("rule", "positive", "negative"):
        if key not in qual:
            raise ValueError(f"{path.name}: assay {aid} qualitative rule needs '{key}'. Add it.")
    rule = qual["rule"]
    if not isinstance(rule, str) or not rule.strip():
        raise ValueError(f"{path.name}: assay {aid} qualitative rule must be a non-empty string. Fix it.")
    for clause in rule.split(" and "):
        m = _CLAUSE.match(clause)
        if not m:
            raise ValueError(f"{path.name}: assay {aid} has bad rule clause {clause!r}. "
                             "Use comparisons like 'b < -4 and hue < 40'.")
        if m.group(1) not in FEATURES:
            raise ValueError(f"{path.name}: assay {aid} rule uses unknown feature {m.group(1)!r}. "
                             f"Use one of {sorted(FEATURES)}.")
    for key in ("positive", "negative"):
        if not isinstance(qual[key], str) or not qual[key].strip():
            raise ValueError(f"{path.name}: assay {aid} qualitative {key} must be a non-empty string. Add it.")
    _validate_bands(entry, path)


def _validate_screenlight(entry: dict[str, Any], path: Path) -> None:
    spec = entry["analysis"]
    aid = entry["id"]
    for key in ("sequence", "bands", "unit"):
        if key not in spec:
            raise ValueError(f"{path.name}: assay {aid} analysis needs '{key}'. Add it.")
    seq = spec["sequence"]
    if not isinstance(seq, list) or not seq or any(not isinstance(c, str) for c in seq):
        raise ValueError(f"{path.name}: assay {aid} analysis.sequence must be a list of colour names. Fix it.")
    if "white" not in seq or "black" not in seq:
        raise ValueError(f"{path.name}: assay {aid} sequence must include white and black. Add them.")
    if not [c for c in seq if c not in ("white", "black")]:
        raise ValueError(f"{path.name}: assay {aid} sequence needs a colour besides white/black. Add one.")
    if not isinstance(spec["unit"], str) or not spec["unit"].strip():
        raise ValueError(f"{path.name}: assay {aid} analysis.unit must be a non-empty string. Add a unit.")
    if "ambient_max" in spec:
        amb = spec["ambient_max"]
        if not isinstance(amb, (int, float)) or isinstance(amb, bool) or not math.isfinite(float(amb)):
            raise ValueError(f"{path.name}: assay {aid} ambient_max must be a number. Fix it.")
    _validate_bands(entry, path)


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
