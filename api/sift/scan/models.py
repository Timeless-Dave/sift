"""Per-target supervised models (docs/scanner.md).

For adulteration and freshness targets, genuine vs adulterated reference scans for the same
food, phone label and owner train a regularised logistic regression on standardised
features. A verdict needs at least MODEL_MIN_TOTAL labelled scans and a stratified
cross-validated accuracy of at least MODEL_MIN_ACCURACY; anything less is "not measured
yet". Cultured-vs-conventional targets are research: they collect scans and never judge.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from ..data.store import PUBLIC, Store
from .schemas import Finding

log = logging.getLogger("sift.scan.models")

MODEL_MIN_PER_CLASS = 6
MODEL_MIN_TOTAL = 20
MODEL_MIN_ACCURACY = 0.8
CV_FOLDS = 5

# Trained models by (food, device, owner, target, reference count, training scan ids). The ids
# make the key exact: the same library never refits, and any new scan trains a fresh model.
_CACHE: dict[tuple, dict[str, Any]] = {}


def _ref_vecs(row: dict) -> dict[str, list[float]]:
    feats = row.get("features")
    return feats if isinstance(feats, dict) else {}


def _common_modalities(rows: list[dict]) -> list[str]:
    """Modalities present with consistent lengths in every training scan."""
    if not rows:
        return []
    first = _ref_vecs(rows[0])
    return [m for m in sorted(first)
            if all(isinstance(_ref_vecs(r).get(m), list) and len(_ref_vecs(r)[m]) == len(first[m]) for r in rows[1:])]


def _matrix(rows: list[dict], modalities: list[str]) -> np.ndarray:
    return np.array([[v for m in modalities for v in _ref_vecs(r)[m]] for r in rows], float)


def _fit(X: np.ndarray, y: np.ndarray) -> tuple[Any, float]:
    """Regularised logistic regression with stratified cross-validation. Returns model and CV accuracy."""
    pipe = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=5000))
    folds = min(CV_FOLDS, min(int((y == 0).sum()), int((y == 1).sum())))
    cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=0)
    accuracy = float(cross_val_score(pipe, X, y, cv=cv, scoring="accuracy").mean())
    return pipe.fit(X, y), accuracy


def _labelled(refs: list[dict], target: str) -> tuple[list[dict], list[dict]]:
    """Genuine scans vs scans adulterated for this target."""
    genuine = [r for r in refs if r.get("label") == "genuine"]
    positive = [r for r in refs if r.get("label") == "adulterated" and r.get("target") == target]
    return genuine, positive


def _classified_finding(target: dict, features: dict[str, list[float]], refs: list[dict], key: tuple) -> Finding:
    """Adulteration/freshness finding: fit on the labelled scans, judge only on enough accurate data."""
    genuine, positive = _labelled(refs, target["id"])
    total = len(genuine) + len(positive)
    short = f"Not measured yet: {total} of {MODEL_MIN_TOTAL} reference scans"
    if len(genuine) < MODEL_MIN_PER_CLASS or len(positive) < MODEL_MIN_PER_CLASS:
        return Finding(target=target["id"], kind=target["kind"], status="no_model", label=short)
    rows = genuine + positive
    modalities = _common_modalities(rows)
    if not modalities or any(m not in features for m in modalities):
        return Finding(target=target["id"], kind=target["kind"], status="no_model", label=short)
    cache_key = (*key, total, tuple(sorted(r["id"] for r in rows)))
    if cache_key not in _CACHE:
        X = _matrix(rows, modalities)
        y = np.array([0] * len(genuine) + [1] * len(positive))
        try:
            model, accuracy = _fit(X, y)
        except ValueError as exc:
            log.info("target model failed to fit", extra={"fields": {"target": target["id"], "why": str(exc)[:120]}})
            return Finding(target=target["id"], kind=target["kind"], status="no_model", label=short)
        _CACHE[cache_key] = {"model": model, "modalities": modalities,
                             "metrics": {"kind": "logistic_regression", "n_genuine": len(genuine),
                                         "n_adulterated": len(positive), "cv_accuracy": round(accuracy, 3),
                                         "cv_folds": min(CV_FOLDS, len(genuine), len(positive)),
                                         "modalities": modalities}}
    entry = _CACHE[cache_key]
    metrics = entry["metrics"]
    if metrics["cv_accuracy"] < MODEL_MIN_ACCURACY or total < MODEL_MIN_TOTAL:
        return Finding(target=target["id"], kind=target["kind"], status="no_model", label=short, model=metrics)
    query = np.array([[v for m in entry["modalities"] for v in features[m]]], float)
    proba = entry["model"].predict_proba(query)[0]
    adulterated = bool(proba[1] >= 0.5)
    label = (f"Model prediction: adulterated for {target['id']}" if adulterated
             else f"Model prediction: genuine for {target['id']}")
    label += f" (cross-validated accuracy {metrics['cv_accuracy']:.2f} on {total} reference scans)."
    return Finding(target=target["id"], kind=target["kind"], status="model", label=label,
                   confidence=round(float(proba[1] if adulterated else proba[0]), 2), model=metrics)


def target_findings(profile: dict, features: dict[str, list[float]], device: str,
                    store: Store, owner: str = PUBLIC) -> list[Finding]:
    """One finding per target in the food profile."""
    refs = store.reference_scans(profile["id"], device, owner)
    out: list[Finding] = []
    for target in profile["targets"]:
        if target["kind"] == "cultured":
            n = sum(1 for r in refs if r.get("target") == target["id"])
            out.append(Finding(target=target["id"], kind="cultured", status="research",
                               label=f"Research: collecting reference scans ({n} so far)"))
        elif target["kind"] in ("adulteration", "freshness"):
            out.append(_classified_finding(target, features, refs, (profile["id"], device, owner, target["id"])))
        else:  # identity targets have no model; the fingerprint match covers them
            out.append(Finding(target=target["id"], kind=target["kind"], status="no_model",
                               label="Not measured yet: no identity model for this food yet."))
    return out
