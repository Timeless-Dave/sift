"""Unit tests on synthetic captures. These check the pipeline's arithmetic (perspective,
colour correction, rules, curves, PLS); they say nothing about accuracy on real food,
which only real-sample validation runs can establish."""

import cv2
import numpy as np
import pytest

from sift.domain import registry
from sift.vision import card, colorimetric, screenlight
from sift.vision.quality import check_screenlight


def photo_of_card(sample_rgb, cast=(1.0, 1.0, 1.0), blur=0):
    img = card.render_card(8, sample_rgb=sample_rgb)
    h, w = img.shape[:2]
    canvas = np.full((1400, 1800, 3), 90, np.uint8)
    H = cv2.getPerspectiveTransform(np.float32([[0, 0], [w, 0], [w, h], [0, h]]),
                                    np.float32([[300, 250], [1500, 320], [1450, 1150], [260, 1080]]))
    cv2.warpPerspective(img, H, (1800, 1400), canvas, borderMode=cv2.BORDER_TRANSPARENT)
    out = np.clip(canvas.astype(float) * np.array(cast)[::-1], 0, 255).astype(np.uint8)
    if blur:
        out = cv2.GaussianBlur(out, (0, 0), blur)
    return out


def expected_lab(rgb):
    return card.linear_to_lab(card.srgb_to_linear(np.array(rgb) / 255.0))


def test_registry_loads_and_cites_sources():
    assays = registry.load_all()
    assert {"olive-oil-screenlight", "milk-starch-iodine", "turmeric-lead-swab"} <= set(assays)
    for a in assays.values():
        assert a["references"], a["id"]


def test_card_svg_has_four_markers_and_window():
    svg = card.card_svg()
    assert svg.startswith("<svg") and "Place sample inside the ring" in svg


@pytest.mark.parametrize("cast", [(1, 1, 1), (1.1, 0.95, 0.8), (0.85, 0.95, 1.12)])
def test_colour_correction_recovers_sample_under_cast(cast):
    rgb = (40, 60, 140)
    reading = card.read_card(photo_of_card(rgb, cast))
    lab, _ = card.window_pixels_lab(reading)
    sel = colorimetric.segment_sample(lab)
    got = np.median(lab[sel], axis=0)
    assert np.linalg.norm(got - expected_lab(rgb)) < 6, got


def test_missing_card_is_reported():
    with pytest.raises(card.CardNotFound):
        card.read_card(np.full((800, 800, 3), 128, np.uint8))


def test_starch_rule_flags_blue_and_passes_brown():
    assay = registry.get("milk-starch-iodine")
    blue = colorimetric.analyze(photo_of_card((45, 50, 110)), assay, None)
    brown = colorimetric.analyze(photo_of_card((205, 165, 95)), assay, None)
    assert blue["status"] == "ok" and blue["verdict"] == "flag"
    assert brown["status"] == "ok" and brown["verdict"] == "pass"


def test_blurry_capture_is_rejected():
    assay = registry.get("milk-starch-iodine")
    res = colorimetric.analyze(photo_of_card((45, 50, 110), blur=2.5), assay, None)
    assert res["status"] == "rejected"
    assert any(p["code"] == "blurry" for p in res["quality"]["problems"])


def test_rule_parser_rejects_code():
    with pytest.raises(ValueError):
        colorimetric.eval_rule("__import__('os')", {"a": 1})


def test_curve_interpolates():
    curve = colorimetric.fit_curve([(0, 0.0), (10, 1.0), (20, 2.0), (21, 2.0)])
    value, inside = colorimetric.apply_curve(curve, 15)
    assert inside and abs(value - 1.5) < 0.1


SEQ = registry.get("olive-oil-screenlight")["analysis"]["sequence"]


def fake_scan(pct, rng, ambient=0.02):
    """Synthetic reflectance that shifts with adulterant percent. Arithmetic test only."""
    frames = {"black": [[ambient] * 3] * 4, "white": [[0.8] * 3] * 4}
    for i, c in enumerate(SEQ[2:]):
        base = 0.2 + 0.03 * i
        frames[c] = [[base + 0.002 * pct + rng.normal(0, 0.002), base - 0.001 * pct, base + 0.0005 * pct]
                     for _ in range(4)]
    return frames


def test_pls_trains_and_predicts():
    rng = np.random.default_rng(0)
    samples = [{"features": screenlight.vectorize(fake_scan(p, rng), SEQ), "known_value": p}
               for p in [0, 0, 10, 10, 20, 20, 30, 30, 50, 50]]
    payload, metrics = screenlight.train(samples)
    assert metrics["r2_cv"] > 0.9
    pred, inside = screenlight.predict(payload, screenlight.vectorize(fake_scan(25, rng), SEQ))
    assert inside and abs(pred - 25) < 5


def test_screenlight_rejects_room_light():
    q = check_screenlight(fake_scan(0, np.random.default_rng(1), ambient=0.3), 0.08)
    assert not q.ok and any(p["code"] == "ambient_light" for p in q.problems)


def test_curve_rejects_levels_with_the_same_reading():
    with pytest.raises(ValueError):
        colorimetric.fit_curve([(5.0, 0.0), (5.0, 1.0), (5.0, 2.0)])


@pytest.mark.parametrize("ext,size", [(".png", (640, 480)), (".jpg", (1200, 900)), (".webp", (700, 500))])
def test_image_size_reads_headers(ext, size):
    from sift.core.security import image_size
    raw = cv2.imencode(ext, np.full((size[1], size[0], 3), 90, np.uint8))[1].tobytes()
    assert image_size(raw) == size


def test_decode_refuses_pixel_bomb():
    from sift.core.errors import TooLarge
    from sift.services.runs import _decode
    png = cv2.imencode(".png", np.full((8000, 8000, 3), 200, np.uint8))[1].tobytes()  # ~200 KB, 64 Mpx
    with pytest.raises(TooLarge):
        _decode(png, 12 * 1024 * 1024)
