"""Colorimetric assays: read a colour reaction in the card window, turn it into features,
then into a result from either a trained calibration curve or the assay's qualitative rule."""

from __future__ import annotations

import math
import operator
import re

import numpy as np

from . import card
from .quality import check_card_capture


def segment_sample(lab: np.ndarray) -> np.ndarray:
    """Separate the sample from white card or paper inside the read circle.

    A pixel belongs to the sample when it sits clearly away from paper white
    (ΔE > 12 from the brightest 20% of pixels in the window)."""
    if lab.shape[0] == 0:
        return np.zeros(0, bool)
    bright = lab[lab[:, 0] >= np.percentile(lab[:, 0], 80)]
    paper = np.median(bright, axis=0)
    de = np.linalg.norm(lab - paper, axis=1)
    sample = de > 12
    # If almost everything differs from "paper", the sample fills the window.
    if sample.mean() > 0.9:
        sample[:] = True
    return sample


def pick_sam_mask(masks: list[np.ndarray], circle: np.ndarray, inside_min: float = 0.8) -> np.ndarray | None:
    """Choose the SAM match that is the sample: most pixels in the read circle, and at least
    `inside_min` of its pixels inside it. This drops the printed ring, the card and stray objects."""
    best, best_n = None, 0
    for m in masks:
        total = int(m.sum())
        n = int((m & circle).sum())
        if total and n / total >= inside_min and n > best_n:
            best, best_n = m, n
    return best


def features_from_lab(lab: np.ndarray) -> dict:
    L, a, b = (float(v) for v in np.median(lab, axis=0))
    chroma = math.hypot(a, b)
    hue = math.degrees(math.atan2(b, a)) % 360
    spread = float(np.median(np.linalg.norm(lab - np.median(lab, axis=0), axis=1)))
    return {
        "L": round(L, 2), "a": round(a, 2), "b": round(b, 2),
        "chroma": round(chroma, 2), "hue": round(hue, 1),
        "blueness": round(-b, 2), "redness": round(a, 2),
        "darkness": round(100 - L, 2), "spread": round(spread, 2),
        "pixels": int(lab.shape[0]),
    }


_OPS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge}
_CLAUSE = re.compile(r"^\s*([a-zA-Z_]+)\s*(<=|>=|<|>)\s*(-?\d+(?:\.\d+)?)\s*$")


def eval_rule(rule: str, feats: dict) -> bool:
    """Evaluate rules like 'a > 20 and hue < 40'. Only 'and' of simple comparisons is allowed."""
    for clause in rule.split(" and "):
        m = _CLAUSE.match(clause)
        if not m:
            raise ValueError(f"Bad rule clause: {clause!r}")
        key, op, val = m.groups()
        if not _OPS[op](float(feats[key]), float(val)):
            return False
    return True


def band_for(value: float, bands: list[dict]) -> dict:
    for band in bands:
        if value <= band["max"]:
            return band
    return bands[-1]


def fit_curve(points: list[tuple[float, float]]) -> dict:
    """Monotone calibration curve: feature value -> concentration, by linear interpolation
    between the mean feature at each known concentration."""
    by_conc: dict[float, list[float]] = {}
    for feat, conc in points:
        by_conc.setdefault(conc, []).append(feat)
    concs = sorted(by_conc)
    if len(concs) < 3:
        raise ValueError("A calibration curve needs samples at 3 or more known levels.")
    xs = [float(np.mean(by_conc[c])) for c in concs]
    order = np.argsort(xs)
    xs_sorted = [xs[i] for i in order]
    cs_sorted = [concs[i] for i in order]
    if any(cs_sorted[i] > cs_sorted[i + 1] for i in range(len(cs_sorted) - 1)) and \
       any(cs_sorted[i] < cs_sorted[i + 1] for i in range(len(cs_sorted) - 1)):
        raise ValueError("Feature does not change steadily with concentration; check the samples.")
    noise = float(np.mean([np.std(v) for v in by_conc.values()]))
    return {"x": xs_sorted, "y": cs_sorted, "noise": round(noise, 3), "levels": len(concs),
            "samples": len(points)}


def apply_curve(curve: dict, x: float) -> tuple[float, bool]:
    xs, ys = curve["x"], curve["y"]
    inside = xs[0] <= x <= xs[-1]
    return float(np.interp(x, xs, ys)), inside


def analyze(image_bgr: np.ndarray, assay: dict, model: dict | None,
            sam_masks: list[np.ndarray] | None = None) -> dict:
    spec = assay["analysis"]
    try:
        reading = card.read_card(image_bgr)
    except card.CardNotFound as exc:
        return {"status": "rejected", "features": {}, "quality": {"ok": False, "metrics": {}, "problems": [{
            "code": "card_not_found", "severity": "reject", "message": str(exc),
            "fix": "Fit the whole card in the frame, hold steady, and make sure all four corner squares show."}]}}
    lab_all, circle = card.window_pixels_lab(reading)
    sample_sel = segment_sample(lab_all)
    used_sam = False
    sam_mask = pick_sam_mask(sam_masks, circle) if sam_masks else None
    if sam_mask is not None and sam_mask.shape == circle.shape:
        sam_in_circle = sam_mask[circle]
        if sam_in_circle.sum() > 0.04 * len(sam_in_circle):
            sample_sel, used_sam = sam_in_circle, True
    sample_mask = np.zeros(circle.shape, bool)
    sample_mask[circle] = sample_sel

    quality = check_card_capture(reading.warped, circle, reading.fit_delta_e, sample_mask)
    feats = features_from_lab(lab_all[sample_sel]) if sample_sel.any() else {}
    out: dict = {"quality": quality.as_dict(), "features": feats,
                 "card": {"fit_delta_e": round(reading.fit_delta_e, 2), "swatches": reading.swatch_measured},
                 "segmentation": "sam-3.1" if used_sam else "card-window"}
    if not quality.ok:
        out["status"] = "rejected"
        return out

    value = feats[spec["feature"]]
    if model and model["kind"] == "curve":
        conc, inside = apply_curve(model["payload"], value)
        band = band_for(conc, spec["bands"])
        noise = model["payload"].get("noise", 0) or 0.0
        span = (max(model["payload"]["x"]) - min(model["payload"]["x"])) or 1.0
        confidence = max(0.05, min(0.97, 1 - 2 * noise / span - (0 if inside else 0.35)))
        out.update(status="ok", mode="calibrated", value=round(conc, 3), unit=spec["unit"],
                   label=band["label"], verdict=band["verdict"], confidence=round(confidence, 2),
                   in_range=inside, model=model["metrics"])
    else:
        rule = spec["qualitative"]
        positive = eval_rule(rule["rule"], feats)
        # Distance from the decision boundary of the first clause gives a rough confidence.
        key, _, thr = _CLAUSE.match(rule["rule"].split(" and ")[0]).groups()
        margin = abs(float(feats[key]) - float(thr))
        confidence = max(0.3, min(0.9, 0.5 + margin / 30))
        out.update(status="ok", mode="qualitative", value=None, unit=None,
                   label=rule["positive"] if positive else rule["negative"],
                   verdict="flag" if positive else "pass", confidence=round(confidence, 2),
                   rule=rule["rule"])
    return out
