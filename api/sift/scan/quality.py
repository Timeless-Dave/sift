"""Quality gates for instant scans (docs/scanner.md).

Each sensing modality is judged usable or not. The scan is rejected only when no requested
modality is usable; otherwise the bad modalities become warnings and the check continues
with the good ones. Motion is a gate only: too much movement rejects the whole scan.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from ..vision.quality import check_screenlight as _vision_screenlight
from .features import SCREEN_SEQUENCE
from .schemas import (
    AcousticCapture,
    BubbleCapture,
    Capture,
    ContactCapture,
    MotionCapture,
    Problem,
    Quality,
    TorchCapture,
    VibrationCapture,
)

SHOP_FIX = {
    "ambient_light": "Press the screen flat against the food or package and cup your hand around the edges.",
    "weak_signal": "Turn screen brightness up and press the screen flat against the food or package.",
    "movement": "Brace your elbow or rest the phone on the shelf, then scan again.",
}
TORCH_CLIPPED_MAX = 0.15
TORCH_DARK_MAX = 0.03
TORCH_EFFECT_MIN = 0.02
SCREENLIGHT_AMBIENT_MAX = 0.08
ACOUSTIC_MARGIN_MIN_DB = 6.0
VIBRATION_RATIO_MIN = 2.0
# The phone reports the 90th-percentile rotation rate, not the single worst spike. These limits are
# first estimates for a hand-held phone (gyro noise and hand tremor alone reach the old 15 deg/s), to
# be tuned from real scans.
MOTION_ROT_MAX_DPS = 45.0
MOTION_ROT_WARN_DPS = 20.0
MOTION_JITTER_MAX = 0.8
MOTION_JITTER_WARN = 0.3
CONTACT_CLIPPED_MAX = 0.3
CONTACT_DARK_WARN = 0.1
BUBBLE_TRACKED_MIN = 0.3
BUBBLE_FPS_MIN = 25.0


def _reject(modality: str, code: str, message: str, fix: str) -> Problem:
    return Problem(modality=modality, code=code, severity="reject", message=message, fix=fix)  # type: ignore[arg-type]


def _warn(modality: str, code: str, message: str, fix: str) -> Problem:
    return Problem(modality=modality, code=code, severity="warn", message=message, fix=fix)  # type: ignore[arg-type]


def check_torch(t: TorchCapture) -> tuple[bool, list[Problem]]:
    """Overexposure, darkness, or a torch that changed nothing (opaque or dark container)."""
    if t.on is None:
        return False, [_reject("torch", "unavailable", "This phone couldn't switch its torch on for the reading.",
                               "Scan with the other sensors, or use a phone with a controllable torch.")]
    problems: list[Problem] = []
    if max(t.on.clipped, t.off.clipped) > TORCH_CLIPPED_MAX:
        problems.append(_reject("torch", "clipped", "The torch reading is overexposed.",
                                "Hold the phone a little further from the food and scan again."))
    if float(np.mean(t.on.mean)) < TORCH_DARK_MAX:
        problems.append(_reject("torch", "too_dark", "The torch reading is too dark to use.",
                                "Hold the phone closer so the flash lights the food, and scan again."))
    elif float(np.mean(np.array(t.on.mean) - np.array(t.off.mean))) < TORCH_EFFECT_MIN:
        problems.append(_reject("torch", "no_effect",
                                "The torch made no difference, so the container may be opaque or very dark.",
                                "Decant into a clear glass if you can, and scan again."))
    return (not problems), problems


def check_screenlight_capture(frames: dict[str, list[list[float]]]) -> tuple[bool, list[Problem]]:
    """Completeness plus the shared screen-light checks (ambient light, weak signal, movement)."""
    missing = [c for c in SCREEN_SEQUENCE if c not in frames]
    if missing:
        return False, [_reject("screenlight", "incomplete",
                               f"The scan is missing the {', '.join(missing[:5])} frames.",
                               "Run the scan again and hold the phone still until it finishes.")]
    report = _vision_screenlight(frames, SCREENLIGHT_AMBIENT_MAX)
    # The lab assay's advice assumes a hood; in a shop the phone itself is the shield.
    problems = [Problem(modality="screenlight", code=p["code"], severity=p["severity"],  # type: ignore[arg-type]
                        message=p["message"], fix=SHOP_FIX.get(p["code"], p["fix"])) for p in report.problems]
    return report.ok, problems


def check_acoustic(a: AcousticCapture) -> tuple[bool, list[Problem]]:
    """The sweep must read clearly above the room noise."""
    margin = float(np.median(np.array(a.response_db, float) - np.array(a.noise_db, float)))
    if margin < ACOUSTIC_MARGIN_MIN_DB:
        return False, [_reject("acoustic", "weak_signal",
                               "The food barely changed the sound, or the shop is too noisy.",
                               "Press the phone firmly against the package, move somewhere quieter and scan again.")]
    return True, []


def check_vibration(v: VibrationCapture) -> tuple[bool, list[Problem]]:
    """The motor-on reading must clearly exceed the resting baseline."""
    if not v.vibrate_available:
        return False, [_reject("vibration", "unavailable", "This phone couldn't vibrate for the reading.",
                               "Scan with the other sensors, or use a phone with vibration.")]
    if float(v.rms_on / max(v.rms_off, 1e-6)) < VIBRATION_RATIO_MIN:
        return False, [_reject("vibration", "no_response", "The vibration reading showed no response from the food.",
                               "Press the phone firmly against the food or jar so they touch, and scan again.")]
    return True, []


def check_contact(c: ContactCapture) -> tuple[bool, list[Problem]]:
    """Torch present, glare bounded, rings falling off with distance; warn on light leaks."""
    if not c.torch_available:
        return False, [_reject("contact", "unavailable", "This phone couldn't switch its torch on for the reading.",
                               "Scan with the other sensors, or use a phone with a controllable torch.")]
    problems: list[Problem] = []
    if float(c.clipped) > CONTACT_CLIPPED_MAX:
        problems.append(_reject("contact", "clipped", "The contact reading has too much glare.",
                                "Press flatter against the food so the torch light spreads evenly, and scan again."))
    if float(np.mean(c.rings[0])) <= float(np.mean(c.rings[-1])):
        problems.append(_reject("contact", "no_falloff",
                                "The rings show no fall-off, so the camera isn't pressed against the food.",
                                "Press the camera flat against the food so no light leaks in, and scan again."))
    if float(np.mean(c.dark)) > CONTACT_DARK_WARN:
        problems.append(_warn("contact", "light_leak", "Light is leaking into the contact reading.",
                              "Press the phone flat against the food so no light leaks in, and scan again."))
    ok = not any(p.severity == "reject" for p in problems)
    return ok, problems


def check_bubble(b: BubbleCapture) -> tuple[bool, list[Problem]]:
    """The bubble must be tracked across the jar with a measured rise time; warn on low frame rates."""
    problems: list[Problem] = []
    if float(b.tracked_fraction) < BUBBLE_TRACKED_MIN:
        problems.append(_reject("bubble", "not_visible",
                                "Sift couldn't see the bubble: fill the frame with the jar and turn it more slowly.",
                                "Fill the frame with the jar and turn it more slowly, then scan again."))
    if b.rise_time_s is None:
        problems.append(_reject("bubble", "no_rise", "The bubble never rose through the jar during the scan.",
                                "Fill the frame with the jar and turn it more slowly, then scan again."))
    if float(b.fps) < BUBBLE_FPS_MIN:
        problems.append(_warn("bubble", "low_fps",
                              "The bubble video ran below 25 fps, so a fast bubble may have been missed.",
                              "Hold still in good light and scan again; honey and syrups read fine at 30 fps."))
    ok = not any(p.severity == "reject" for p in problems)
    return ok, problems


def check_motion(m: MotionCapture) -> list[Problem]:
    """Too much movement rejects the scan, since it corrupts every other modality."""
    if m.max_rotation_dps > MOTION_ROT_MAX_DPS or m.accel_jitter > MOTION_JITTER_MAX:
        return [_reject("motion", "movement", "The phone moved too much during the scan.",
                        "Rest your hands on something steady, hold the phone still and scan again.")]
    if m.max_rotation_dps > MOTION_ROT_WARN_DPS or m.accel_jitter > MOTION_JITTER_WARN:
        return [_warn("motion", "some_movement", "The phone moved a little during the scan.",
                      "Brace your elbow or rest the phone on the shelf for a steadier reading.")]
    return []


def check_capture(capture: Capture, profile: dict) -> tuple[Quality, set[str]]:
    """Judge the capture against the food profile. Returns the quality report and the usable modalities."""
    modalities: list[str] = profile["scan"]["modalities"]
    food: str = profile["name"]
    gates: dict[str, Callable[[Capture], tuple[bool, list[Problem]]]] = {
        "torch": lambda c: check_torch(c.torch),  # type: ignore[arg-type]
        "screenlight": lambda c: check_screenlight_capture(  # type: ignore[arg-type]
            {k: [list(map(float, rgb)) for rgb in rows] for k, rows in c.screenlight.frames.items()}),
        "acoustic": lambda c: check_acoustic(c.acoustic),  # type: ignore[arg-type]
        "vibration": lambda c: check_vibration(c.vibration),  # type: ignore[arg-type]
        "contact": lambda c: check_contact(c.contact),  # type: ignore[arg-type]
        "bubble": lambda c: check_bubble(c.bubble),  # type: ignore[arg-type]
    }
    problems: list[Problem] = []
    usable: set[str] = set()
    for modality in sorted(m for m in gates if getattr(capture, m) is not None and m not in modalities):
        problems.append(Problem(modality=modality, code="ignored", severity="warn",  # type: ignore[arg-type]
                                message=f"The {modality} capture isn't used for {food} and was ignored.",
                                fix=f"Nothing to fix: this check uses {', '.join(modalities)}."))
    for modality in modalities:
        if getattr(capture, modality, None) is None:
            continue
        ok, found = gates[modality](capture)
        problems.extend(found)
        if ok:
            usable.add(modality)
    if capture.motion is not None:
        motion = check_motion(capture.motion)
        problems.extend(motion)
        if any(p.severity == "reject" for p in motion):
            usable.clear()
    if usable:  # some modalities are good: the bad ones become warnings
        return Quality(ok=True, problems=[p if p.severity == "warn" else p.model_copy(update={"severity": "warn"})
                                          for p in problems]), usable
    if not any(p.severity == "reject" for p in problems):
        problems.append(_reject("scan", "no_usable_modality", f"Sift couldn't use any capture for {food}.",
                                f"{profile['scan']['placement']} Hold still and scan again."))
    return Quality(ok=False, problems=problems), set()
