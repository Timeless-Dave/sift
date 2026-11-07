"""Robustness: bad YAML, bad models and odd input fail with 4xx or startup errors, not 500s."""

import numpy as np
import pytest

from sift.core.config import Settings
from sift.core.errors import InvalidInput
from sift.domain import registry
from sift.vision import colorimetric, screenlight
from sift.vision.quality import check_screenlight
from tests.test_api import post_card
from tests.test_core import fake_scan, photo_of_card


def _col_assay(**over):
    base = {
        "id": "test-col", "name": "t", "food": "f", "status": "experimental", "method": "colorimetric",
        "references": [{"title": "t"}],
        "protocol": [{"id": "a", "title": "t", "instruction": "i"},
                     {"id": "photo", "title": "p", "instruction": "i", "capture": "card"}],
        "analysis": {
            "feature": "blueness", "unit": "x",
            "bands": [{"max": 1, "label": "a", "verdict": "pass"}, {"max": 2, "label": "b", "verdict": "flag"}],
            "qualitative": {"rule": "b < -4", "positive": "y", "negative": "n"},
        },
    }
    base["analysis"].update(over.pop("analysis", {}))
    base.update(over)
    return base


def _sl_assay(**over):
    base = {
        "id": "test-sl", "name": "t", "food": "f", "status": "experimental", "method": "screenlight",
        "references": [{"title": "t"}],
        "protocol": [{"id": "a", "title": "t", "instruction": "i"},
                     {"id": "scan", "title": "s", "instruction": "i", "capture": "screenlight"}],
        "analysis": {
            "sequence": ["white", "black", "red"], "unit": "%",
            "bands": [{"max": 5, "label": "a", "verdict": "pass"}, {"max": 100, "label": "b", "verdict": "flag"}],
        },
    }
    base["analysis"].update(over.pop("analysis", {}))
    base.update(over)
    return base


# M4 ---------------------------------------------------------------------------
def test_empty_yaml_is_skipped(tmp_path, monkeypatch):
    from pathlib import Path

    good = ('id: t1\nname: t\nfood: f\nstatus: planned\nmethod: colorimetric\n'
            'references:\n  - title: t\n')
    (tmp_path / "a.yaml").write_text(good)
    (tmp_path / "empty.yaml").write_text("")
    (tmp_path / "blank.yaml").write_text("\n# only a comment\n")
    monkeypatch.setattr(registry, "ASSAY_DIR", Path(tmp_path))
    registry.load_all.cache_clear()
    try:
        assert "t1" in registry.load_all()
    finally:
        registry.load_all.cache_clear()


def test_malformed_yaml_raises_valueerror(tmp_path, monkeypatch):
    from pathlib import Path

    (tmp_path / "bad.yaml").write_text("[unclosed\n")
    monkeypatch.setattr(registry, "ASSAY_DIR", Path(tmp_path))
    registry.load_all.cache_clear()
    try:
        with pytest.raises(ValueError, match="bad.yaml.*invalid YAML"):
            registry.load_all()
    finally:
        registry.load_all.cache_clear()


def test_non_dict_entry_raises_valueerror(tmp_path, monkeypatch):
    from pathlib import Path

    (tmp_path / "bad.yaml").write_text("- just a string\n")
    monkeypatch.setattr(registry, "ASSAY_DIR", Path(tmp_path))
    registry.load_all.cache_clear()
    try:
        with pytest.raises(ValueError, match="must be a mapping"):
            registry.load_all()
    finally:
        registry.load_all.cache_clear()


# M5 ---------------------------------------------------------------------------
def test_registry_rejects_bad_rules_bands_and_sequences(tmp_path):
    from pathlib import Path

    p = Path("x.yaml")
    with pytest.raises(ValueError, match="bad rule"):
        registry._validate(_col_assay(analysis={"qualitative": {"rule": "blueness >> 3", "positive": "y",
                                                                        "negative": "n"}}), p)
    with pytest.raises(ValueError, match="bands must be a non-empty"):
        registry._validate(_col_assay(analysis={"bands": []}), p)
    with pytest.raises(ValueError, match="unknown feature"):
        registry._validate(_col_assay(analysis={"feature": "nosuch"}), p)
    with pytest.raises(ValueError, match="white and black"):
        registry._validate(_sl_assay(analysis={"sequence": ["red", "green"]}), p)
    with pytest.raises(ValueError, match="besides white/black"):
        registry._validate(_sl_assay(analysis={"sequence": ["white", "black"]}), p)
    with pytest.raises(ValueError, match="sorted by increasing max"):
        registry._validate(_col_assay(analysis={"bands": [{"max": 2, "label": "a", "verdict": "pass"},
                                                                  {"max": 1, "label": "b",
                                                                   "verdict": "flag"}]}), p)
    with pytest.raises(ValueError, match="unknown method"):
        registry._validate(_col_assay(method="microscopy"), p)
    with pytest.raises(ValueError, match="needs 'feature'"):
        bad = _col_assay()
        del bad["analysis"]["feature"]
        registry._validate(bad, p)


# M6 ---------------------------------------------------------------------------
def test_screenlight_train_rejects_bad_shapes():
    good_vec = [0.1] * 6
    samples = [{"features": [0.1 + v * 0.002 + i * 0.001 for i in range(6)], "known_value": float(v)}
               for v in [0, 0, 10, 10, 20, 20]]
    with pytest.raises(ValueError, match="non-empty feature vectors"):
        screenlight.train([{"features": 3.5, "known_value": 0.0} for _ in range(6)])
    with pytest.raises(ValueError, match="non-empty feature vectors"):
        screenlight.train([{"features": [], "known_value": float(v)} for v in [0, 0, 10, 10, 20, 20]])
    mixed = [{"features": good_vec, "known_value": 0.0} for _ in range(3)]
    mixed += [{"features": good_vec + [0.1], "known_value": 10.0} for _ in range(3)]
    with pytest.raises(ValueError, match="different vector lengths"):
        screenlight.train(mixed)
    assert screenlight.train(samples)  # sanity: valid shapes still train


def test_screenlight_train_failure_is_422(client):
    for i in range(3):  # too few levels for a curve, but screenlight needs 6 scans/3 levels
        run_id = client.post("/v1/runs/screenlight", json={
            "assay_id": "olive-oil-screenlight", "device": "d1",
            "frames": fake_scan(0, np.random.default_rng(i))}).json()["run_id"]
        client.post("/v1/calibration/samples", json={"run_id": run_id, "known_value": 0})
    r = client.post("/v1/calibration/train", json={"assay_id": "olive-oil-screenlight", "device": "d1"})
    assert r.status_code == 422


def test_fit_curve_rejects_non_numeric():
    with pytest.raises(ValueError, match="must be numbers"):
        colorimetric.fit_curve([([1, 2], 0.0), ([1, 2], 1.0), ([1, 2], 2.0)])


# M7/M8 ------------------------------------------------------------------------
def test_dim_mismatch_returns_needs_calibration():
    assay = registry.get("olive-oil-screenlight")
    frames = fake_scan(10, np.random.default_rng(0))
    rng = np.random.default_rng(1)
    seq = assay["analysis"]["sequence"]
    samples = [{"features": screenlight.vectorize(fake_scan(p, rng), seq), "known_value": p}
               for p in [0, 0, 10, 10, 20, 20, 30, 30, 50, 50]]
    payload, metrics = screenlight.train(samples)
    dim = len(payload["x_mean"])
    assert dim == 30
    bad = dict(payload, x_mean=payload["x_mean"][:10])  # sequence edited after training
    out = screenlight.analyze(frames, assay, {"kind": "pls", "payload": bad, "metrics": metrics})
    assert out["status"] == "needs_calibration"


def test_wrong_kind_model_is_treated_as_no_model():
    oil = registry.get("olive-oil-screenlight")
    frames = fake_scan(10, np.random.default_rng(0))
    curve_model = {"kind": "curve", "payload": {"x": [0, 1, 2], "y": [0, 1, 2]}, "metrics": {}}
    assert screenlight.analyze(frames, oil, curve_model)["status"] == "needs_calibration"
    assert screenlight.analyze(frames, oil, {"kind": "pls", "payload": {}, "metrics": {}})["status"] \
        == "needs_calibration"

    milk = registry.get("milk-starch-iodine")
    img = photo_of_card((45, 50, 110))
    pls_model = {"kind": "pls", "payload": {"x_mean": [0]}, "metrics": {}}
    assert colorimetric.analyze(img, milk, pls_model)["mode"] == "qualitative"
    bad_curve = {"kind": "curve", "payload": {"x": [1], "y": [1]}, "metrics": {}}
    assert colorimetric.analyze(img, milk, bad_curve)["mode"] == "qualitative"


# L1 ---------------------------------------------------------------------------
def test_device_label_with_trailing_space_finds_model(client):
    from tests.test_calibration import calibrate, scan

    calibrate(client, device="lab-phone")
    assert scan(client, 25, 99, device="lab-phone ")["status"] == "ok"
    state = client.get("/v1/calibration/olive-oil-screenlight", params={"device": "lab-phone "}).json()
    assert state["model"] is not None


# L15 --------------------------------------------------------------------------
def test_unknown_step_id_is_422(client):
    r = client.post("/v1/agent/turn", json={"assay_id": "milk-starch-iodine", "step_id": "nope",
                                            "message": "hello"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_input"
    r = client.post("/v1/agent/turn", json={"assay_id": "milk-starch-iodine", "message": "hello"})
    assert r.status_code == 200 and r.json()["step_id"] == "boil"


# L16 --------------------------------------------------------------------------
def test_qualitative_truth_must_be_0_or_1(client):
    run_id = post_card(client).json()["run_id"]  # qualitative: value is None
    assert client.post(f"/v1/runs/{run_id}/truth", json={"value": 0.5}).status_code == 422
    assert client.post(f"/v1/runs/{run_id}/truth", json={"value": 1}).status_code == 200


def test_numeric_truth_allows_fractions(client):
    from tests.test_calibration import calibrate, scan

    calibrate(client, device="lab-phone")
    run_id = scan(client, 25, 99)["run_id"]  # calibrated screenlight: numeric value
    assert client.post(f"/v1/runs/{run_id}/truth", json={"value": 25.5}).status_code == 200


# L18 --------------------------------------------------------------------------
def test_missing_colour_is_422_and_direct_check_still_fails():
    frames = fake_scan(0, np.random.default_rng(0))
    del frames["red"]
    from sift.core.config import Settings
    from sift.services.runs import validate_frames

    with pytest.raises(InvalidInput):
        validate_frames(frames, registry.get("olive-oil-screenlight"), Settings())
    q = check_screenlight({"red": [[[0.2, 0.2, 0.2]]]}, 0.08)
    assert not q.ok and any(p["code"] == "incomplete" for p in q.problems)


# L19 --------------------------------------------------------------------------
def test_path_and_query_ids_are_pattern_checked(client):
    assert client.get("/v1/runs", params={"assay_id": "../../etc"}).status_code == 422
    assert client.get("/v1/runs/not-a-run!!").status_code == 422
    assert client.get("/v1/assays/NOTVALID!!").status_code == 422
    assert client.get("/v1/calibration/NOTVALID!!", params={"device": "x"}).status_code == 422
    r = client.post("/v1/runs/not-a-run!!/truth", json={"value": 1})
    assert r.status_code == 422


# L22 --------------------------------------------------------------------------
def test_create_app_validates_settings(tmp_path):
    from sift.http.app import create_app

    bad = Settings(env="production", cors_origins=("*",), db_path=tmp_path / "t.db")
    with pytest.raises(ValueError, match="SIFT_CORS"):
        create_app(bad)
    bad = Settings(meta_base_url="http://insecure", db_path=tmp_path / "t2.db")
    with pytest.raises(ValueError, match="META_BASE_URL"):
        create_app(bad)


def test_create_app_fails_fast_on_bad_registry(tmp_path, monkeypatch):
    from pathlib import Path

    from sift.http.app import create_app

    (tmp_path / "bad.yaml").write_text("- just a string\n")
    monkeypatch.setattr(registry, "ASSAY_DIR", Path(tmp_path))
    registry.load_all.cache_clear()
    try:
        with pytest.raises(ValueError, match="must be a mapping"):
            create_app(Settings(db_path=tmp_path / "t.db"))
    finally:
        registry.load_all.cache_clear()
