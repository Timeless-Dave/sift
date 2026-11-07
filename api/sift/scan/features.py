"""Per-modality feature vectors from a phone capture (docs/scanner.md).

Each function turns one capture modality into a plain list of floats for the reference
library. A modality with no capture, or a capture a vector can't be built from, yields no
vector (None) instead of a guess.
"""

from __future__ import annotations

import numpy as np

from ..vision import screenlight
from .schemas import AcousticCapture, Capture, ScreenlightCapture, TorchCapture, VibrationCapture

# The screen colours every food uses, in flash order. Same sequence as the olive-oil
# screen-light assay, so screen-light vectors stay comparable across foods.
SCREEN_SEQUENCE = ["white", "black", "red", "orange", "yellow", "lime", "green", "teal", "cyan", "blue", "violet",
                   "magenta"]
TORCH_DIM = 14
RATIO_CAP = 100.0


def torch_vector(t: TorchCapture) -> list[float] | None:
    """Ambient-subtracted reflectance, its chromaticity, both spreads and both clipped fractions."""
    if t.on is None:  # no controllable torch: no reflectance to report
        return None
    on, off = np.array(t.on.mean, float), np.array(t.off.mean, float)
    reflectance = on - off
    total = float(reflectance.clip(min=0).sum())
    chroma = (reflectance.clip(min=0) / total).tolist() if total > 1e-6 else [1 / 3, 1 / 3, 1 / 3]
    return [*reflectance.tolist(), *chroma, *t.on.std, *t.off.std, float(t.on.clipped), float(t.off.clipped)]


def screenlight_vector(s: ScreenlightCapture) -> list[float] | None:
    """Dark-subtracted, white-normalised reflectance per screen colour, in sequence order."""
    try:
        frames = {colour: [list(map(float, rgb)) for rgb in rows] for colour, rows in s.frames.items()}
        return [float(v) for v in screenlight.vectorize(frames, SCREEN_SEQUENCE)]
    except (ValueError, TypeError, ArithmeticError):
        return None


def acoustic_vector(a: AcousticCapture) -> list[float]:
    """Per-band transmission (response over noise), level-normalised so phone volume matters less."""
    transmission = np.array(a.response_db, float) - np.array(a.noise_db, float)
    return (transmission - float(np.median(transmission))).tolist()


def vibration_vector(v: VibrationCapture) -> list[float]:
    """How much stronger the vibration reads with the motor on, plus the normalised spectrum."""
    ratio = float(v.rms_on / max(v.rms_off, 1e-6))
    vec = [min(ratio, RATIO_CAP)]
    if v.spectrum:
        peak = max(max(v.spectrum), 1e-9)
        vec.extend(float(x / peak) for x in v.spectrum)
    return vec


def extract_features(capture: Capture, modalities: set[str] | None = None) -> dict[str, list[float]]:
    """Feature vectors for the usable modalities. Missing modalities produce no vector."""
    want = modalities if modalities is not None else {"torch", "screenlight", "acoustic", "vibration"}
    vecs: dict[str, list[float]] = {}
    if "torch" in want and capture.torch is not None and (v := torch_vector(capture.torch)) is not None:
        vecs["torch"] = v
    if "screenlight" in want and capture.screenlight is not None and (
            v := screenlight_vector(capture.screenlight)) is not None:
        vecs["screenlight"] = v
    if "acoustic" in want and capture.acoustic is not None:
        vecs["acoustic"] = acoustic_vector(capture.acoustic)
    if "vibration" in want and capture.vibration is not None:
        vecs["vibration"] = vibration_vector(capture.vibration)
    return vecs
