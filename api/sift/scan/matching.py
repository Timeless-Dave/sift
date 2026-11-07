"""Reference library comparison (docs/scanner.md).

A check scan is compared with the genuine reference scans for the same food, phone label
and owner. Below MIN_GENUINE references there is no verdict. Otherwise each feature is
standardised with a robust centre and scale from the genuine references, distances are
computed per modality and combined, and the threshold comes from the genuine references'
own leave-one-out distances.
"""

from __future__ import annotations

import numpy as np

from ..data.store import PUBLIC, Store
from .schemas import Match

MIN_GENUINE = 5
SCALE_FLOOR = 1e-3
THRESHOLD_MARGIN = 1.5
THRESHOLD_FLOOR = 0.5
LOO_PERCENTILE = 95.0


def genuine_references(store: Store, food: str, device: str, owner: str = PUBLIC) -> list[dict]:
    """Genuine reference scans for one food, phone label and owner, oldest first."""
    return [r for r in store.reference_scans(food, device, owner) if r.get("label") == "genuine"]


def _common_modalities(scan: dict[str, list[float]], refs: list[dict]) -> list[str]:
    """Modalities in the scan and in every genuine reference, with matching vector lengths."""
    common = []
    for modality in sorted(scan):
        vec = scan[modality]
        if all(isinstance(r.get("features"), dict) and isinstance(r["features"].get(modality), list)
               and len(r["features"][modality]) == len(vec) for r in refs):
            common.append(modality)
    return common


def _standardise(matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Robust per-feature centre (median) and scale (MAD), with a floor on scale."""
    centre = np.median(matrix, axis=0)
    mad = np.median(np.abs(matrix - centre), axis=0)
    return centre, np.maximum(1.4826 * mad, SCALE_FLOOR)


def _modality_distance(vec: list[float], refs: np.ndarray) -> float:
    """RMS z-distance of one vector from reference rows, standardised by the references."""
    centre, scale = _standardise(refs)
    return float(np.sqrt(np.mean(((np.array(vec, float) - centre) / scale) ** 2)))


def _combined(scan: dict[str, list[float]], refs: list[dict], modalities: list[str]) -> float:
    """Per-modality RMS z-distances combined as their root mean square."""
    dists = [_modality_distance(scan[m], np.array([r["features"][m] for r in refs], float)) for m in modalities]
    return float(np.sqrt(np.mean(np.square(dists))))


def compare(scan: dict[str, list[float]], refs: list[dict]) -> Match:
    """Compare scan features with genuine references. No verdict below MIN_GENUINE."""
    if len(refs) < MIN_GENUINE:
        return Match(status="no_reference", n_genuine=len(refs), modalities=sorted(scan))
    modalities = _common_modalities(scan, refs)
    if not modalities:
        return Match(status="no_reference", n_genuine=len(refs), modalities=sorted(scan))
    distance = _combined(scan, refs, modalities)
    loo = [_combined(r["features"], refs[:i] + refs[i + 1:], modalities) for i, r in enumerate(refs)]
    threshold = max(float(np.percentile(loo, LOO_PERCENTILE)) * THRESHOLD_MARGIN, THRESHOLD_FLOOR)
    status = "matches" if distance <= threshold else "differs"
    return Match(status=status, distance=distance, threshold=threshold, n_genuine=len(refs), modalities=modalities)
