import os

import cv2
import numpy as np
import pytest

os.environ.pop("MODEL_API_KEY", None)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SIFT_DB", str(tmp_path / "t.db"))
    import importlib

    import sift.main as main
    importlib.reload(main)
    from fastapi.testclient import TestClient
    return TestClient(main.app)


def test_health_reports_offline_agent(client):
    assert client.get("/health").json()["agent"] == "offline"


def test_assays_list(client):
    data = client.get("/v1/assays").json()
    ids = {a["id"]: a for a in data}
    assert ids["milk-starch-iodine"]["runnable"] is True
    assert ids["honey-pollen-origin"]["runnable"] is False


def test_card_run_end_to_end_and_truth(client):
    from tests.test_core import photo_of_card
    ok, jpg = cv2.imencode(".jpg", photo_of_card((45, 50, 110)), [cv2.IMWRITE_JPEG_QUALITY, 92])
    r = client.post("/v1/runs/card", data={"assay_id": "milk-starch-iodine", "device": "test-phone"},
                    files={"image": ("c.jpg", jpg.tobytes(), "image/jpeg")})
    body = r.json()
    assert r.status_code == 200, body
    assert body["verdict"] == "flag" and body["report"]["agent"] == "offline"
    t = client.post(f"/v1/runs/{body['run_id']}/truth", json={"value": 1}).json()
    assert t["accuracy"]["n"] == 1


def test_planned_assay_not_runnable(client):
    r = client.post("/v1/runs/screenlight", json={"assay_id": "beef-pork-screenlight", "frames": {}})
    assert r.status_code == 409


def test_screenlight_without_model_asks_for_calibration(client):
    from tests.test_core import fake_scan
    frames = fake_scan(10, np.random.default_rng(2))
    r = client.post("/v1/runs/screenlight", json={"assay_id": "olive-oil-screenlight", "frames": frames})
    assert r.json()["status"] == "needs_calibration"


def test_agent_offline_advances_step(client):
    r = client.post("/v1/agent/turn", json={"assay_id": "milk-starch-iodine", "step_id": "boil", "message": "done"})
    assert r.json()["step_id"] == "mix"
