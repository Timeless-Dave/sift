"""Capture quality checks. These run in code before any model sees the image, so a blurry
or badly lit capture is rejected the same way every time."""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass
class QualityReport:
    ok: bool = True
    problems: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    def fail(self, code: str, message: str, fix: str) -> None:
        self.ok = False
        self.problems.append({"code": code, "severity": "reject", "message": message, "fix": fix})

    def warn(self, code: str, message: str, fix: str) -> None:
        self.problems.append({"code": code, "severity": "warn", "message": message, "fix": fix})

    def as_dict(self) -> dict:
        return {"ok": self.ok, "problems": self.problems, "metrics": self.metrics}


BLUR_MIN = 60.0
CLIPPED_MAX = 0.15
CARD_FIT_MAX = 9.0
GLARE_MAX = 0.2


def check_card_capture(warped_bgr: np.ndarray, window_mask: np.ndarray, fit_delta_e: float,
                       sample_mask: np.ndarray | None) -> QualityReport:
    q = QualityReport()
    gray = cv2.cvtColor(warped_bgr, cv2.COLOR_BGR2GRAY)
    sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    win = warped_bgr[sample_mask] if sample_mask is not None and sample_mask.any() else warped_bgr[window_mask]
    clipped = float(np.mean(np.any(win >= 250, axis=1) & np.all(win >= 245, axis=1)))
    q.metrics.update(sharpness=round(sharp, 1), clipped_fraction=round(clipped, 3),
                     card_fit_delta_e=round(fit_delta_e, 2))

    if sharp < BLUR_MIN:
        q.fail("blurry", "The photo is out of focus.", "Hold the phone steady and tap the card to focus.")
    if fit_delta_e > CARD_FIT_MAX:
        q.fail("lighting", "The card's colour swatches don't line up with their printed colours.",
               "Move to even daylight or white light and avoid coloured lamps and shadows.")
    elif fit_delta_e > CARD_FIT_MAX / 2:
        q.warn("lighting", "Lighting is uneven, so colour accuracy is reduced.",
               "Avoid shadows across the card.")
    if sample_mask is not None:
        area = float(sample_mask.sum()) / max(1, int(window_mask.sum()))
        q.metrics["sample_area_fraction"] = round(area, 3)
        if area < 0.04:
            q.fail("no_sample", "No sample was found inside the ring.", "Place the sample in the middle of the ring.")
        glare = float(np.mean(np.all(warped_bgr[sample_mask] >= 245, axis=1))) if sample_mask.any() else 0.0
        q.metrics["glare_fraction"] = round(glare, 3)
        if glare > GLARE_MAX:
            q.fail("glare", "Reflections are washing out the sample.", "Tilt the phone slightly or turn off the flash.")
    elif clipped > CLIPPED_MAX:
        q.fail("overexposed", "The sample area is overexposed.", "Turn off the flash or move away from direct light.")
    return q


def check_screenlight(frames: dict[str, list[list[float]]], ambient_max: float) -> QualityReport:
    """frames: colour name -> list of mean [r, g, b] (0-1) per captured frame."""
    q = QualityReport()
    dark = np.array(frames.get("black") or [[1, 1, 1]]).mean(axis=0)
    white = np.array(frames.get("white") or [[0, 0, 0]]).mean(axis=0)
    ambient = float(dark.mean())
    signal = float((white - dark).mean())
    jitter = max((float(np.array(v).std(axis=0).mean()) for v in frames.values() if len(v) > 1), default=0.0)
    q.metrics.update(ambient=round(ambient, 4), signal=round(signal, 4), jitter=round(jitter, 4),
                     frames=sum(len(v) for v in frames.values()))
    if ambient > ambient_max:
        q.fail("ambient_light", "Room light is reaching the sample.", "Close the hood or move somewhere darker.")
    if signal < 0.05:
        q.fail("weak_signal", "The screen light barely reached the sample.",
               "Move the phone closer to the sample and turn screen brightness to maximum.")
    if jitter > 0.04:
        q.fail("movement", "The phone or sample moved during the scan.", "Rest the phone in the hood and scan again.")
    missing = [c for c in ("white", "black") if c not in frames]
    if missing:
        q.fail("incomplete", f"The scan is missing the {', '.join(missing)} frames.", "Run the scan again.")
    return q
