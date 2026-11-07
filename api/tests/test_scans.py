"""Instant-scan tests on synthetic captures. These check the pipeline's arithmetic and
wiring (features, gates, matching, models, scoping); they say nothing about accuracy on
real food, which only real-sample reference scans can establish."""

import math
import re

import numpy as np
import pytest

from sift.agent import guardrails
from sift.domain import foods, registry
from sift.scan import features as F
from sift.scan.matching import MIN_GENUINE
from sift.scan.quality import check_capture
from sift.scan.schemas import Capture, TorchCapture

SEQ = F.SCREEN_SEQUENCE
BINS = [200.0, 400.0, 800.0, 1600.0, 3200.0, 6400.0, 12800.0, 20000.0]
BANNED_WORDS = re.compile(r"\b(safe|pure|fake)\b", re.IGNORECASE)


def torch_cap(rng, shift=0.0, clipped=0.0):
    off = [float(0.10 + rng.normal(0, 0.003)) for _ in range(3)]
    on = [float(v + shift + rng.normal(0, 0.003)) for v in (0.50, 0.45, 0.40)]
    return {"off": {"mean": off, "std": [0.01, 0.01, 0.01], "clipped": 0.0},
            "on": {"mean": on, "std": [0.01, 0.01, 0.01], "clipped": float(clipped)},
            "torch_available": True}


def screen_frames(rng, pct=0.0, ambient=0.02, frames_per=3):
    frames = {"black": [[ambient] * 3] * frames_per, "white": [[0.8] * 3] * frames_per}
    for i, colour in enumerate(SEQ[2:]):
        base = 0.2 + 0.03 * i
        frames[colour] = [[float(base + 0.002 * pct + rng.normal(0, 0.002)),
                           float(base - 0.001 * pct + rng.normal(0, 0.002)),
                           float(base + 0.0005 * pct + rng.normal(0, 0.002))] for _ in range(frames_per)]
    return frames


def acoustic_cap(rng, margin=20.0):
    noise = [float(-60 + rng.normal(0, 0.5)) for _ in BINS]
    response = [float(n + margin + rng.normal(0, 0.5)) for n in noise]
    return {"sample_rate": 48000, "bins_hz": list(BINS), "response_db": response, "noise_db": noise}


def vibration_cap(rng):
    spectrum = [float(0.5 * math.exp(-i / 6) + rng.normal(0, 0.005)) for i in range(16)]
    return {"rate_hz": 60.0, "rms_on": 0.8, "rms_off": 0.05, "spectrum": spectrum, "vibrate_available": True}


def motion_cap():
    return {"max_rotation_dps": 4.2, "accel_jitter": 0.03}


def full_capture(rng, shift=0.0, pct=0.0):
    return {"torch": torch_cap(rng, shift=shift), "screenlight": {"frames": screen_frames(rng, pct=pct)},
            "motion": motion_cap()}


def post_scan(client, capture, food="olive-oil", device="test-phone", mode="check", reference=None, headers=None):
    body = {"food": food, "device": device, "mode": mode, "capture": capture}
    if reference is not None:
        body["reference"] = reference
    return client.post("/v1/scans", json=body, headers=headers or {})


def store_genuine(client, n, seed=0, device="test-phone", headers=None, **kw):
    rng = np.random.default_rng(seed)
    ids = []
    for _ in range(n):
        r = post_scan(client, full_capture(rng, **kw), device=device, mode="reference",
                      reference={"label": "genuine"}, headers=headers)
        assert r.status_code == 200, r.json()
        assert r.json()["status"] == "stored"
        ids.append(r.json()["scan_id"])
    return ids


def test_screen_sequence_matches_assay():
    assert registry.get("olive-oil-screenlight")["analysis"]["sequence"] == SEQ


def test_features_cover_every_modality():
    rng = np.random.default_rng(7)
    cap = Capture.model_validate({"torch": torch_cap(rng), "screenlight": {"frames": screen_frames(rng)},
                                  "acoustic": acoustic_cap(rng), "vibration": vibration_cap(rng),
                                  "motion": motion_cap()})
    vecs = F.extract_features(cap)
    assert set(vecs) == {"torch", "screenlight", "acoustic", "vibration"}
    assert len(vecs["torch"]) == F.TORCH_DIM == 14
    assert len(vecs["screenlight"]) == (len(SEQ) - 2) * 3 == 30
    assert len(vecs["acoustic"]) == len(BINS)
    assert abs(float(np.median(vecs["acoustic"]))) < 1e-9  # level-normalised
    assert len(vecs["vibration"]) == 17 and vecs["vibration"][0] > 2  # ratio, then spectrum


def test_features_skip_missing_modalities():
    rng = np.random.default_rng(7)
    cap = Capture.model_validate({"torch": torch_cap(rng)})
    assert set(F.extract_features(cap)) == {"torch"}
    assert F.extract_features(cap, {"screenlight"}) == {}
    dark = torch_cap(rng)
    dark["on"] = None
    dark["torch_available"] = False
    assert F.torch_vector(TorchCapture.model_validate(dark)) is None


def test_schema_rejections(client):
    only_motion = {"motion": motion_cap()}
    assert post_scan(client, only_motion).status_code == 422
    bad_lengths = acoustic_cap(np.random.default_rng(0))
    bad_lengths["response_db"] = bad_lengths["response_db"][:-1]
    assert post_scan(client, {"acoustic": bad_lengths}).status_code == 422
    bad_bins = acoustic_cap(np.random.default_rng(0))
    bad_bins["bins_hz"] = sorted(bad_bins["bins_hz"], reverse=True)
    assert post_scan(client, {"acoustic": bad_bins}).status_code == 422
    rng = np.random.default_rng(0)
    assert post_scan(client, full_capture(rng), mode="reference").status_code == 422  # no label
    assert post_scan(client, full_capture(rng), reference={"label": "genuine"}).status_code == 422  # check + label
    assert post_scan(client, full_capture(rng), food="../../etc").status_code == 422
    assert post_scan(client, full_capture(rng), food="no-such-food").status_code == 404


def test_quality_torch_gates():
    profile = foods.get("olive-oil")
    rng = np.random.default_rng(1)
    bad_clipped = Capture.model_validate({"torch": torch_cap(rng, clipped=0.9)})
    quality, usable = check_capture(bad_clipped, profile)
    assert not quality.ok and not usable
    assert [p.code for p in quality.problems] == ["clipped"]
    dark = torch_cap(rng)
    dark["on"]["mean"] = [0.01, 0.01, 0.01]
    quality, _ = check_capture(Capture.model_validate({"torch": dark}), profile)
    assert [p.code for p in quality.problems] == ["too_dark"]
    opaque = torch_cap(rng)
    opaque["off"]["mean"] = [0.40, 0.40, 0.40]
    opaque["on"]["mean"] = [0.41, 0.41, 0.41]
    quality, _ = check_capture(Capture.model_validate({"torch": opaque}), profile)
    assert [p.code for p in quality.problems] == ["no_effect"]
    no_torch = torch_cap(rng)
    no_torch["on"] = None
    no_torch["torch_available"] = False
    quality, _ = check_capture(Capture.model_validate({"torch": no_torch}), profile)
    assert [p.code for p in quality.problems] == ["unavailable"]


def test_quality_warns_and_continues_with_good_modalities():
    profile = foods.get("olive-oil")
    rng = np.random.default_rng(2)
    mixed = Capture.model_validate({"torch": torch_cap(rng, clipped=0.9),
                                    "screenlight": {"frames": screen_frames(rng)}})
    quality, usable = check_capture(mixed, profile)
    assert quality.ok and usable == {"screenlight"}
    assert [(p.modality, p.severity) for p in quality.problems] == [("torch", "warn")]


def test_quality_other_modalities():
    profile = foods.get("olive-oil")
    rng = np.random.default_rng(3)
    bright = Capture.model_validate({"screenlight": {"frames": screen_frames(rng, ambient=0.3)}})
    quality, usable = check_capture(bright, profile)
    assert not quality.ok and [p.code for p in quality.problems] == ["ambient_light"]
    frames = screen_frames(rng)
    del frames["red"]
    quality, _ = check_capture(Capture.model_validate({"screenlight": {"frames": frames}}), profile)
    assert [p.code for p in quality.problems] == ["incomplete"]
    all_band_profile = {"name": "test", "scan": {"modalities": ["torch", "screenlight", "acoustic", "vibration"],
                                                "placement": "Hold still."}}
    weak = Capture.model_validate({"acoustic": acoustic_cap(rng, margin=1.0)})
    quality, _ = check_capture(weak, all_band_profile)
    assert [p.code for p in quality.problems] == ["weak_signal"]
    dead = vibration_cap(rng)
    dead["rms_on"] = 0.05
    quality, _ = check_capture(Capture.model_validate({"vibration": dead}), all_band_profile)
    assert [p.code for p in quality.problems] == ["no_response"]
    still = vibration_cap(rng)
    still["vibrate_available"] = False
    quality, _ = check_capture(Capture.model_validate({"vibration": still}), all_band_profile)
    assert [p.code for p in quality.problems] == ["unavailable"]
    moved = Capture.model_validate({"torch": torch_cap(rng), "screenlight": {"frames": screen_frames(rng)},
                                    "motion": {"max_rotation_dps": 60.0, "accel_jitter": 0.03}})
    quality, usable = check_capture(moved, profile)
    assert not quality.ok and not usable
    assert "movement" in [p.code for p in quality.problems]


def test_extra_modality_ignored_with_warn(client):
    rng = np.random.default_rng(4)
    capture = full_capture(rng) | {"acoustic": acoustic_cap(rng)}
    body = post_scan(client, capture).json()
    assert body["status"] == "ok"
    assert [(p["modality"], p["code"], p["severity"]) for p in body["quality"]["problems"]] == [
        ("acoustic", "ignored", "warn")]
    assert "acoustic" not in body["match"]["modalities"]


def test_only_ignored_modalities_rejects(client):
    rng = np.random.default_rng(4)
    body = post_scan(client, {"acoustic": acoustic_cap(rng)}).json()
    assert body["status"] == "rejected" and not body["quality"]["ok"]
    assert "no_usable_modality" in [p["code"] for p in body["quality"]["problems"]]


def test_no_reference_below_five(client):
    rng = np.random.default_rng(5)
    for want in range(1, MIN_GENUINE):
        r = post_scan(client, full_capture(rng), mode="reference", reference={"label": "genuine"})
        assert r.json()["match"]["n_genuine"] == want
    body = post_scan(client, full_capture(rng)).json()
    assert body["status"] == "ok"
    assert body["match"]["status"] == "no_reference"
    assert body["match"]["n_genuine"] == MIN_GENUINE - 1
    assert body["match"]["distance"] is None and body["match"]["threshold"] is None


def test_matches_then_differs(client):
    store_genuine(client, 8, seed=6)
    rng = np.random.default_rng(60)
    fresh = post_scan(client, full_capture(rng)).json()
    assert fresh["match"]["status"] == "matches", fresh["match"]
    assert fresh["match"]["n_genuine"] == 8
    assert fresh["match"]["modalities"] == ["screenlight", "torch"]
    assert fresh["match"]["distance"] <= fresh["match"]["threshold"]
    shifted = post_scan(client, full_capture(rng, shift=0.2, pct=50)).json()
    assert shifted["match"]["status"] == "differs", shifted["match"]
    assert "Mixed with a cheaper seed oil" in shifted["report"]["text"]


def test_model_appears_only_with_labels_and_accuracy(client):
    device = "model-phone"
    rng = np.random.default_rng(8)
    for _ in range(6):
        assert post_scan(client, full_capture(rng), device=device, mode="reference",
                         reference={"label": "genuine"}).status_code == 200
    for _ in range(6):
        ref = {"label": "adulterated", "target": "seed-oil-dilution"}
        assert post_scan(client, full_capture(rng, shift=0.08, pct=30), device=device, mode="reference",
                         reference=ref).status_code == 200
    promised = post_scan(client, full_capture(rng), device=device).json()["findings"][0]
    assert promised["target"] == "seed-oil-dilution" and promised["status"] == "no_model"
    assert promised["label"] == "Not measured yet: 12 of 20 reference scans"
    assert promised["model"]["kind"] == "logistic_regression"
    assert (promised["model"]["n_genuine"], promised["model"]["n_adulterated"]) == (6, 6)
    assert promised["model"]["cv_accuracy"] >= 0.8
    for _ in range(4):
        post_scan(client, full_capture(rng), device=device, mode="reference", reference={"label": "genuine"})
    for _ in range(4):
        ref = {"label": "adulterated", "target": "seed-oil-dilution"}
        post_scan(client, full_capture(rng, shift=0.08, pct=30), device=device, mode="reference", reference=ref)
    judged = post_scan(client, full_capture(rng), device=device).json()["findings"][0]
    assert judged["status"] == "model", judged
    assert judged["confidence"] is not None and judged["confidence"] >= 0.8
    assert judged["model"]["cv_accuracy"] >= 0.8
    assert (judged["model"]["n_genuine"], judged["model"]["n_adulterated"]) == (10, 10)


def test_model_stays_no_model_on_random_labels(client):
    device = "random-phone"
    rng = np.random.default_rng(9)
    for _ in range(10):
        post_scan(client, full_capture(rng), device=device, mode="reference", reference={"label": "genuine"})
    for _ in range(10):
        ref = {"label": "adulterated", "target": "seed-oil-dilution"}
        post_scan(client, full_capture(rng), device=device, mode="reference", reference=ref)
    finding = post_scan(client, full_capture(rng), device=device).json()["findings"][0]
    assert finding["status"] == "no_model", finding
    assert finding["model"]["cv_accuracy"] < 0.8


CULTURED_PROFILE = {
    "id": "test-beef", "name": "Test beef", "category": "meat", "aliases": ["beef"],
    "scan": {"modalities": ["torch", "screenlight"], "placement": "Press the phone against the pack."},
    "targets": [{"id": "cultured-check", "kind": "cultured", "question": "Cultured or conventional?",
                 "status": "research", "signals": {"torch": "colour may differ."},
                 "likely_causes": ["A different production method"],
                 "references": [{"title": "t", "source": "s", "url": "https://example.com", "finding": "f"}]}],
    "references": [{"title": "t", "source": "s", "url": "https://example.com", "finding": "f"}],
}


def test_cultured_stays_research(client, monkeypatch):
    monkeypatch.setattr(foods, "load_all", lambda: {"test-beef": CULTURED_PROFILE})
    rng = np.random.default_rng(10)
    for _ in range(10):
        ref = {"label": "cultured", "target": "cultured-check"}
        assert post_scan(client, full_capture(rng), food="test-beef", device="culture-phone",
                         mode="reference", reference=ref).status_code == 200
    for _ in range(10):
        ref = {"label": "conventional", "target": "cultured-check"}
        assert post_scan(client, full_capture(rng, shift=0.1, pct=40), food="test-beef", device="culture-phone",
                         mode="reference", reference=ref).status_code == 200
    body = post_scan(client, full_capture(rng), food="test-beef", device="culture-phone").json()
    assert body["match"]["status"] == "no_reference"
    assert body["findings"] == [{"target": "cultured-check", "kind": "cultured", "status": "research",
                                 "label": "Research: collecting reference scans (20 so far)", "confidence": None,
                                 "model": None}]


def _minted_key(client):
    return client.post("/v1/keys", json={"owner": "lab"}, headers={"X-Admin-Token": "x" * 30}).json()["key"]


def test_owner_scoping(make_client):
    client = make_client(SIFT_ADMIN_TOKEN="x" * 30)
    key = _minted_key(client)
    headers = {"X-Sift-Key": key}
    store_genuine(client, 5, seed=11, headers=headers)
    rng = np.random.default_rng(61)
    assert post_scan(client, full_capture(rng)).json()["match"]["n_genuine"] == 0  # public library is empty
    assert post_scan(client, full_capture(rng), headers=headers).json()["match"]["status"] == "matches"
    keyed_id = client.get("/v1/scans", headers=headers).json()[0]["id"]
    assert client.get(f"/v1/scans/{keyed_id}").status_code == 404
    assert client.get(f"/v1/scans/{keyed_id}", headers=headers).status_code == 200
    assert keyed_id not in {s["id"] for s in client.get("/v1/scans").json()}


def test_reference_mode_protected(make_client):
    client = make_client(SIFT_PROTECT_CALIBRATION=1, SIFT_ADMIN_TOKEN="z" * 30)
    rng = np.random.default_rng(12)
    assert post_scan(client, full_capture(rng), mode="reference", reference={"label": "genuine"}).status_code == 401
    assert post_scan(client, full_capture(rng)).status_code == 200  # checks stay open
    key = client.post("/v1/keys", json={"owner": "lab"}, headers={"X-Admin-Token": "z" * 30}).json()["key"]
    r = post_scan(client, full_capture(rng), mode="reference", reference={"label": "genuine"},
                  headers={"X-Sift-Key": key})
    assert r.status_code == 200 and r.json()["status"] == "stored"


def test_rejected_scans_stay_out_of_the_library(client):
    store_genuine(client, 5, seed=13)
    rng = np.random.default_rng(62)
    bad = Capture.model_validate({"torch": torch_cap(rng),
                                          "screenlight": {"frames": screen_frames(rng, ambient=0.3)}}).model_dump()
    bad["torch"]["on"]["mean"] = [0.01, 0.01, 0.01]  # too dark, and the screen-light is washed out
    rejected = post_scan(client, bad, mode="reference", reference={"label": "genuine"}).json()
    assert rejected["status"] == "rejected"
    assert post_scan(client, full_capture(rng)).json()["match"]["n_genuine"] == 5
    assert "test-phone" in client.get("/v1/foods/olive-oil").json()["counts"]["by_device"]


def test_scan_get_and_filter(client):
    rng = np.random.default_rng(14)
    check_id = post_scan(client, full_capture(rng)).json()["scan_id"]
    ref_id = post_scan(client, full_capture(rng), mode="reference", reference={"label": "genuine"}).json()["scan_id"]
    listed = client.get("/v1/scans").json()
    assert {s["id"] for s in listed} == {check_id, ref_id}
    assert len(client.get("/v1/scans", params={"food": "olive-oil"}).json()) == 2
    assert client.get("/v1/scans", params={"food": "no-such-food"}).json() == []
    one = client.get(f"/v1/scans/{check_id}").json()
    assert one["id"] == check_id and one["food"] == "olive-oil" and one["result"]["status"] == "ok"
    assert client.get("/v1/scans/deadbeef1234").status_code == 404


def test_foods_endpoints(client):
    entry = client.get("/v1/foods").json()[0]
    assert (entry["id"], entry["name"], entry["category"]) == ("olive-oil", "Olive oil", "oil")
    assert entry["aliases"] and entry["scan"]["modalities"] == ["screenlight", "torch"]
    assert entry["targets"][0]["status"] == "experimental"
    assert entry["targets"][0]["reference_scans"] == 0
    assert entry["counts"] == {"references": 0, "genuine": 0, "by_device": {}, "by_target": {}}
    rng = np.random.default_rng(15)
    store_genuine(client, 2, seed=15)
    ref = {"label": "adulterated", "target": "seed-oil-dilution"}
    post_scan(client, full_capture(rng, shift=0.08, pct=30), mode="reference", reference=ref)
    detail = client.get("/v1/foods/olive-oil").json()
    assert detail["counts"]["references"] == 3 and detail["counts"]["genuine"] == 2
    assert detail["counts"]["by_device"] == {"test-phone": {"references": 3, "genuine": 2}}
    assert detail["counts"]["by_target"] == {"seed-oil-dilution": {"adulterated": 1}}
    assert detail["targets"][0]["reference_scans"] == 1
    assert detail["targets"][0]["likely_causes"]
    assert client.get("/v1/foods/no-such-food").status_code == 404


def test_reports_never_claim(client):
    rng = np.random.default_rng(16)
    stored = post_scan(client, full_capture(rng), mode="reference", reference={"label": "genuine"}).json()
    texts = [stored["report"]["text"]]
    assert stored["report"]["agent"] == "offline"
    texts.append(post_scan(client, full_capture(rng)).json()["report"]["text"])  # no_reference
    bad = Capture.model_validate(full_capture(rng)).model_dump()
    bad["motion"] = {"max_rotation_dps": 60.0, "accel_jitter": 0.03}
    texts.append(post_scan(client, bad).json()["report"]["text"])  # rejected
    store_genuine(client, 4, seed=17)
    texts.append(post_scan(client, full_capture(rng)).json()["report"]["text"])  # matches
    texts.append(post_scan(client, full_capture(rng, shift=0.2, pct=50)).json()["report"]["text"])  # differs
    assert len(texts) == 5
    for text in texts:
        assert BANNED_WORDS.search(text) is None, text
        assert guardrails._BANNED_RE.search(text) is None, text


def test_motion_rejects_scan(client):
    rng = np.random.default_rng(18)
    bad = Capture.model_validate(full_capture(rng)).model_dump()
    bad["motion"] = {"max_rotation_dps": 60.0, "accel_jitter": 0.03}
    body = post_scan(client, bad).json()
    assert body["status"] == "rejected" and not body["quality"]["ok"]
    assert "movement" in [p["code"] for p in body["quality"]["problems"]]


@pytest.mark.parametrize("label", ["genuine", "adulterated", "cultured", "conventional"])
def test_reference_labels_round_trip(client, label):
    rng = np.random.default_rng(19)
    ref = {"label": label, "target": "seed-oil-dilution", "value": 20, "note": "lab-mixed"}
    body = post_scan(client, full_capture(rng), mode="reference", reference=ref).json()
    assert body["status"] == "stored"
    row = client.get(f"/v1/scans/{body['scan_id']}").json()
    assert (row["label"], row["target"], row["value"]) == (label, "seed-oil-dilution", 20)
