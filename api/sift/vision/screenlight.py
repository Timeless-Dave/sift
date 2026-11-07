"""Screen-light assays (after Song et al., Ulster University): the phone screen shows a
sequence of colours, the front camera records the sample, and the reflected colour under
each illuminant becomes a spectrum-like vector. A partial least squares model trained on
samples of known composition predicts the target value."""

from __future__ import annotations

import numpy as np
from sklearn.cross_decomposition import PLSRegression
from sklearn.model_selection import KFold, LeaveOneOut, cross_val_predict

from .colorimetric import band_for
from .quality import check_screenlight

MAX_LOO_SAMPLES = 200


def vectorize(frames: dict[str, list[list[float]]], sequence: list[str]) -> list[float]:
    """Dark-subtracted, white-normalised mean RGB per illuminant, in sequence order."""
    dark = np.array(frames["black"]).mean(axis=0)
    white = np.array(frames["white"]).mean(axis=0) - dark
    white = np.where(white < 1e-3, 1e-3, white)
    vec: list[float] = []
    for colour in sequence:
        if colour in ("white", "black"):
            continue
        if colour not in frames:
            raise ValueError(f"Scan is missing the {colour} frames.")
        rgb = (np.array(frames[colour]).mean(axis=0) - dark) / white
        vec.extend(float(v) for v in rgb)
    return vec


def train(samples: list[dict]) -> tuple[dict, dict]:
    X = np.array([s["features"] for s in samples], float)
    y = np.array([s["known_value"] for s in samples], float)
    if len(samples) < 6 or len(set(y)) < 3:
        raise ValueError("Training needs at least 6 scans across 3 or more known levels.")
    if len(samples) > MAX_LOO_SAMPLES:
        cv, validation = KFold(n_splits=5, shuffle=True, random_state=0), "5-fold cross-validation"
    else:
        cv, validation = LeaveOneOut(), "leave-one-out cross-validation"
    n_comp = int(min(5, X.shape[1], len(samples) - 2))
    best = None
    for k in range(1, n_comp + 1):
        pred = cross_val_predict(PLSRegression(n_components=k, scale=True), X, y, cv=cv).ravel()
        rmse = float(np.sqrt(np.mean((pred - y) ** 2)))
        if best is None or rmse < best[1]:
            best = (k, rmse, pred)
    k, rmse, pred = best
    ss_res = float(np.sum((pred - y) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2)) or 1.0
    pls = PLSRegression(n_components=k, scale=True).fit(X, y)
    payload = {
        "x_mean": pls._x_mean.tolist(), "x_std": pls._x_std.tolist(),
        "y_mean": np.atleast_1d(pls._y_mean).tolist(),
        "coef": np.asarray(pls.coef_).reshape(-1).tolist(),
        "intercept": float(np.ravel(getattr(pls, "intercept_", [0.0]))[0]),
        "x_min": X.min(axis=0).tolist(), "x_max": X.max(axis=0).tolist(),
        "y_min": float(y.min()), "y_max": float(y.max()), "rmse_cv": rmse,
    }
    metrics = {"components": k, "samples": len(samples), "levels": len(set(y)),
               "rmse_cv": round(rmse, 3), "r2_cv": round(1 - ss_res / ss_tot, 3), "validation": validation}
    return payload, metrics


def predict(payload: dict, vec: list[float]) -> tuple[float, bool]:
    x = np.array(vec, float)
    # Mirrors PLSRegression.predict (sklearn >= 1.3): centre X only, coef_ already absorbs scaling.
    pred = float((x - np.array(payload["x_mean"])) @ np.array(payload["coef"]) + payload["intercept"])
    lo, hi = np.array(payload["x_min"]), np.array(payload["x_max"])
    pad = 0.15 * (hi - lo + 1e-6)
    inside = bool(np.all(x >= lo - pad) and np.all(x <= hi + pad))
    return pred, inside


def analyze(frames: dict, assay: dict, model: dict | None) -> dict:
    spec = assay["analysis"]
    quality = check_screenlight(frames, spec.get("ambient_max", 0.08))
    out: dict = {"quality": quality.as_dict()}
    if not quality.ok:
        out["status"] = "rejected"
        return out
    vec = vectorize(frames, spec["sequence"])
    out["features"] = {"vector": [round(v, 5) for v in vec]}
    if not model:
        out.update(status="needs_calibration",
                   label="This phone has no trained model for this test yet.",
                   verdict="unknown",
                   next_step="In Researcher mode, scan samples with known mixing levels and train a model.")
        return out
    value, inside = predict(model["payload"], vec)
    value = float(np.clip(value, 0, 100))
    band = band_for(value, spec["bands"])
    span = (model["payload"]["y_max"] - model["payload"]["y_min"]) or 1.0
    confidence = max(0.05, min(0.95, 1 - 2 * model["payload"]["rmse_cv"] / span - (0 if inside else 0.4)))
    out.update(status="ok", mode="calibrated", value=round(value, 1), unit=spec["unit"],
               label=band["label"], verdict=band["verdict"], confidence=round(confidence, 2),
               in_range=inside, model=model["metrics"])
    return out
