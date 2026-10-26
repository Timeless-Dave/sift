"""The Sift reference card: a printed card with four ArUco corner markers, eight colour
swatches and a sample window. Every colorimetric capture includes the card, so Sift can
undo perspective and correct colour for the phone's camera and the room's light.

All geometry is in millimetres on the card.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

CARD_W, CARD_H = 120.0, 80.0
MARKER_MM = 14.0
MARGIN_MM = 4.0
ARUCO_DICT = cv2.aruco.DICT_4X4_50
# Marker id -> which of its own corners sits on the card's outer corner, and where that is.
# OpenCV returns marker corners clockwise from top-left.
MARKER_ANCHORS = {
    0: (0, (MARGIN_MM, MARGIN_MM)),
    1: (1, (CARD_W - MARGIN_MM, MARGIN_MM)),
    2: (2, (CARD_W - MARGIN_MM, CARD_H - MARGIN_MM)),
    3: (3, (MARGIN_MM, CARD_H - MARGIN_MM)),
}

# Nominal sRGB of each printed swatch. Correction maps what the camera saw onto these.
SWATCHES: list[tuple[str, tuple[int, int, int]]] = [
    ("white", (255, 255, 255)),
    ("light-grey", (192, 192, 192)),
    ("mid-grey", (128, 128, 128)),
    ("black", (24, 24, 24)),
    ("red", (220, 40, 40)),
    ("green", (40, 170, 70)),
    ("blue", (40, 70, 200)),
    ("yellow", (240, 210, 40)),
]
SWATCH_W, SWATCH_H, SWATCH_GAP = 14.0, 10.0, 3.0
SWATCH_X0, SWATCH_Y0 = 26.0, 6.0
WINDOW_CENTER = (60.0, 55.0)
WINDOW_R = 14.0          # printed ring
WINDOW_READ_R = 10.0     # area actually read, clear of the ring


def swatch_rects() -> list[tuple[str, tuple[int, int, int], tuple[float, float, float, float]]]:
    out = []
    for i, (name, rgb) in enumerate(SWATCHES):
        col, row = i % 4, i // 4
        x = SWATCH_X0 + col * (SWATCH_W + SWATCH_GAP)
        y = SWATCH_Y0 + row * (SWATCH_H + SWATCH_GAP)
        out.append((name, rgb, (x, y, SWATCH_W, SWATCH_H)))
    return out


def _marker_bits(marker_id: int) -> np.ndarray:
    dictionary = cv2.aruco.getPredefinedDictionary(ARUCO_DICT)
    return cv2.aruco.generateImageMarker(dictionary, marker_id, 6)  # 4x4 bits + 1-cell border


# ---------------------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------------------

def card_svg() -> str:
    """Printable card at true size (print at 100%, no scaling)."""
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{CARD_W}mm" height="{CARD_H}mm" '
        f'viewBox="0 0 {CARD_W} {CARD_H}">',
        f'<rect width="{CARD_W}" height="{CARD_H}" fill="#fff"/>',
    ]
    for marker_id, (_, (ax, ay)) in MARKER_ANCHORS.items():
        x0 = ax if ax < CARD_W / 2 else ax - MARKER_MM
        y0 = ay if ay < CARD_H / 2 else ay - MARKER_MM
        bits = _marker_bits(marker_id)
        cell = MARKER_MM / bits.shape[0]
        for r in range(bits.shape[0]):
            for c in range(bits.shape[1]):
                if bits[r, c] == 0:
                    parts.append(f'<rect x="{x0 + c * cell:.3f}" y="{y0 + r * cell:.3f}" '
                                 f'width="{cell + 0.02:.3f}" height="{cell + 0.02:.3f}" fill="#000"/>')
    for _, (r, g, b), (x, y, w, h) in swatch_rects():
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="rgb({r},{g},{b})" '
                     'stroke="#999" stroke-width="0.15"/>')
    cx, cy = WINDOW_CENTER
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{WINDOW_R}" fill="none" stroke="#000" stroke-width="0.6"/>')
    parts.append(f'<text x="{cx}" y="{cy + WINDOW_R + 4.5}" font-family="sans-serif" font-size="3" '
                 'text-anchor="middle">Place sample inside the ring</text>')
    parts.append(f'<text x="{CARD_W / 2}" y="{SWATCH_Y0 + 2 * SWATCH_H + SWATCH_GAP + 5}" font-family="sans-serif" '
                 'font-size="3.2" font-weight="bold" text-anchor="middle">Sift reference card v1</text>')
    parts.append("</svg>")
    return "".join(parts)


def render_card(px_per_mm: float = 8.0, sample_rgb: tuple[int, int, int] | None = None) -> np.ndarray:
    """Bitmap of the card in BGR, used by tests and as a reference image."""
    w, h = int(CARD_W * px_per_mm), int(CARD_H * px_per_mm)
    img = np.full((h, w, 3), 255, np.uint8)
    for marker_id, (_, (ax, ay)) in MARKER_ANCHORS.items():
        x0 = ax if ax < CARD_W / 2 else ax - MARKER_MM
        y0 = ay if ay < CARD_H / 2 else ay - MARKER_MM
        size = int(round(MARKER_MM * px_per_mm))
        bits = cv2.resize(_marker_bits(marker_id), (size, size), interpolation=cv2.INTER_NEAREST)
        px, py = int(round(x0 * px_per_mm)), int(round(y0 * px_per_mm))
        img[py:py + size, px:px + size] = bits[..., None]
    for _, (r, g, b), (x, y, sw, sh) in swatch_rects():
        p0 = (int(x * px_per_mm), int(y * px_per_mm))
        p1 = (int((x + sw) * px_per_mm), int((y + sh) * px_per_mm))
        cv2.rectangle(img, p0, p1, (b, g, r), -1)
    cx, cy = (int(v * px_per_mm) for v in WINDOW_CENTER)
    cv2.circle(img, (cx, cy), int(WINDOW_R * px_per_mm), (0, 0, 0), max(1, int(0.6 * px_per_mm)))
    if sample_rgb is not None:
        r, g, b = sample_rgb
        cv2.circle(img, (cx, cy), int(7 * px_per_mm), (b, g, r), -1)
    return img


# ---------------------------------------------------------------------------------------
# Reading a capture
# ---------------------------------------------------------------------------------------

class CardNotFound(ValueError):
    pass


@dataclass
class CardReading:
    warped: np.ndarray            # BGR, card rectified to px_per_mm
    px_per_mm: float
    correction: np.ndarray        # 4x3 affine in linear RGB
    fit_delta_e: float            # mean ΔE of swatches after correction
    swatch_measured: list[tuple[str, list[float]]]


def detect_and_rectify(image_bgr: np.ndarray, px_per_mm: float = 8.0) -> np.ndarray:
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    detector = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(ARUCO_DICT),
                                       cv2.aruco.DetectorParameters())
    corners, ids, _ = detector.detectMarkers(gray)
    found: dict[int, np.ndarray] = {}
    if ids is not None:
        for c, i in zip(corners, ids.flatten()):
            if int(i) in MARKER_ANCHORS:
                found[int(i)] = c.reshape(4, 2)
    if len(found) < 4:
        missing = sorted(set(MARKER_ANCHORS) - set(found))
        raise CardNotFound(f"Found {len(found)} of 4 corner squares (missing {missing}).")
    src = np.array([found[i][MARKER_ANCHORS[i][0]] for i in range(4)], np.float32)
    dst = np.array([[x * px_per_mm, y * px_per_mm] for _, (x, y) in (MARKER_ANCHORS[i] for i in range(4))],
                   np.float32)
    H = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(image_bgr, H, (int(CARD_W * px_per_mm), int(CARD_H * px_per_mm)))


def srgb_to_linear(rgb: np.ndarray) -> np.ndarray:
    c = np.clip(rgb, 0, 1)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_lab(lin: np.ndarray) -> np.ndarray:
    m = np.array([[0.4124564, 0.3575761, 0.1804375],
                  [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]])
    xyz = np.clip(lin, 0, None) @ m.T
    xyz = xyz / np.array([0.95047, 1.0, 1.08883])
    eps, k = 216 / 24389, 24389 / 27
    f = np.where(xyz > eps, np.cbrt(xyz), (k * xyz + 16) / 116)
    L = 116 * f[..., 1] - 16
    a = 500 * (f[..., 0] - f[..., 1])
    b = 200 * (f[..., 1] - f[..., 2])
    return np.stack([L, a, b], axis=-1)


def _bgr_to_linear(pixels_bgr: np.ndarray) -> np.ndarray:
    rgb = pixels_bgr[..., ::-1].astype(np.float64) / 255.0
    return srgb_to_linear(rgb)


def _rect_pixels(img: np.ndarray, rect_mm, px_per_mm: float, inset_mm: float = 2.0) -> np.ndarray:
    x, y, w, h = rect_mm
    x0, y0 = int((x + inset_mm) * px_per_mm), int((y + inset_mm) * px_per_mm)
    x1, y1 = int((x + w - inset_mm) * px_per_mm), int((y + h - inset_mm) * px_per_mm)
    return img[y0:y1, x0:x1].reshape(-1, 3)


def fit_correction(warped: np.ndarray, px_per_mm: float) -> tuple[np.ndarray, float, list]:
    measured, target, report = [], [], []
    for name, rgb, rect in swatch_rects():
        px = _bgr_to_linear(_rect_pixels(warped, rect, px_per_mm))
        m = np.median(px, axis=0)
        measured.append(m)
        target.append(srgb_to_linear(np.array(rgb) / 255.0))
        report.append((name, [round(float(v), 4) for v in m]))
    X = np.hstack([np.array(measured), np.ones((len(measured), 1))])
    Y = np.array(target)
    M, *_ = np.linalg.lstsq(X, Y, rcond=None)
    corrected = X @ M
    de = np.linalg.norm(linear_to_lab(corrected) - linear_to_lab(Y), axis=1)
    return M, float(de.mean()), report


def read_card(image_bgr: np.ndarray, px_per_mm: float = 8.0) -> CardReading:
    warped = detect_and_rectify(image_bgr, px_per_mm)
    M, de, report = fit_correction(warped, px_per_mm)
    return CardReading(warped, px_per_mm, M, de, report)


def window_pixels_lab(reading: CardReading, mask: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Colour-corrected Lab of every pixel in the read area, plus the boolean circle mask."""
    h, w = reading.warped.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    cx, cy = (v * reading.px_per_mm for v in WINDOW_CENTER)
    circle = (xx - cx) ** 2 + (yy - cy) ** 2 <= (WINDOW_READ_R * reading.px_per_mm) ** 2
    if mask is not None:
        circle &= mask.astype(bool)
    lin = _bgr_to_linear(reading.warped[circle])
    X = np.hstack([lin, np.ones((lin.shape[0], 1))])
    lab = linear_to_lab(np.clip(X @ reading.correction, 0, 1))
    return lab, circle
