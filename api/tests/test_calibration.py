"""Calibration and accuracy integrity: samples and models stay with their owner, and no run is
both a calibration sample and a validation run."""

import sqlite3

import numpy as np

from tests.test_api import post_card
from tests.test_core import fake_scan

OIL = "olive-oil-screenlight"
ADMIN = "z" * 30


def scan(client, pct, seed, device="lab-phone", headers=None):
    body = {"assay_id": OIL, "device": device, "frames": fake_scan(pct, np.random.default_rng(seed))}
    return client.post("/v1/runs/screenlight", json=body, headers=headers or {}).json()


def calibrate(client, headers=None, device="lab-phone"):
    for i, pct in enumerate([0, 0, 10, 10, 20, 20, 30, 30, 50, 50]):
        run_id = scan(client, pct, i, device, headers)["run_id"]
        r = client.post("/v1/calibration/samples", json={"run_id": run_id, "known_value": pct}, headers=headers or {})
        assert r.status_code == 200, r.json()
    r = client.post("/v1/calibration/train", json={"assay_id": OIL, "device": device}, headers=headers or {})
    assert r.status_code == 200, r.json()


def test_calibration_sample_cannot_become_validation_run(client):
    run_id = post_card(client).json()["run_id"]
    assert client.post("/v1/calibration/samples", json={"run_id": run_id, "known_value": 1}).status_code == 200
    r = client.post(f"/v1/runs/{run_id}/truth", json={"value": 1})
    assert r.status_code == 409 and "calibration" in r.json()["error"]["message"]


def test_run_cannot_be_added_twice(client):
    run_id = post_card(client).json()["run_id"]
    assert client.post("/v1/calibration/samples", json={"run_id": run_id, "known_value": 1}).status_code == 200
    assert client.post("/v1/calibration/samples", json={"run_id": run_id, "known_value": 1}).status_code == 409


def test_keyed_calibration_is_private_to_its_key(make_client):
    c = make_client(SIFT_ADMIN_TOKEN=ADMIN)
    key = c.post("/v1/keys", json={"owner": "lab"}, headers={"X-Admin-Token": ADMIN}).json()["key"]
    h = {"X-Sift-Key": key}
    calibrate(c, h)

    assert c.get(f"/v1/calibration/{OIL}", params={"device": "lab-phone"}, headers=h).json()["model"]
    public = c.get(f"/v1/calibration/{OIL}", params={"device": "lab-phone"}).json()
    assert public["model"] is None and public["samples"] == []

    # The key's model reads the key's runs; a public run on the same phone label stays uncalibrated.
    assert scan(c, 25, 99, headers=h)["status"] == "ok"
    assert scan(c, 25, 99)["status"] == "needs_calibration"
    assert c.get(f"/v1/assays/{OIL}").json()["models"] == []
    assert len(c.get(f"/v1/assays/{OIL}", headers=h).json()["models"]) == 1


def test_public_calibration_does_not_reach_keyed_runs(make_client):
    c = make_client(SIFT_ADMIN_TOKEN=ADMIN)
    key = c.post("/v1/keys", json={"owner": "lab"}, headers={"X-Admin-Token": ADMIN}).json()["key"]
    calibrate(c)
    assert scan(c, 25, 99)["status"] == "ok"
    assert scan(c, 25, 99, headers={"X-Sift-Key": key})["status"] == "needs_calibration"


def test_calibration_state_requires_key_when_server_does(make_client):
    c = make_client(SIFT_REQUIRE_KEY=1)
    assert c.get(f"/v1/calibration/{OIL}", params={"device": "x"}).status_code == 401


def test_accuracy_is_reported_per_phone_and_per_owner(make_client):
    c = make_client(SIFT_ADMIN_TOKEN=ADMIN)
    key = c.post("/v1/keys", json={"owner": "lab"}, headers={"X-Admin-Token": ADMIN}).json()["key"]
    for device, truth in [("phone-a", 1), ("phone-a", 1), ("phone-b", 0)]:
        run_id = post_card(c, device=device).json()["run_id"]  # blue sample: flagged
        c.post(f"/v1/runs/{run_id}/truth", json={"value": truth})
    keyed = post_card(c, headers={"X-Sift-Key": key}, device="phone-c").json()["run_id"]
    c.post(f"/v1/runs/{keyed}/truth", json={"value": 1}, headers={"X-Sift-Key": key})

    acc = c.get("/v1/assays/milk-starch-iodine").json()["accuracy"]
    assert acc["n"] == 3 and set(acc["by_device"]) == {"phone-a", "phone-b"}
    assert acc["by_device"]["phone-a"]["agreement"] == 1.0 and acc["by_device"]["phone-b"]["agreement"] == 0.0

    mine = c.get("/v1/assays/milk-starch-iodine", headers={"X-Sift-Key": key}).json()["accuracy"]
    assert mine["n"] == 1 and set(mine["by_device"]) == {"phone-c"}


def test_v02_database_is_migrated(tmp_path, monkeypatch):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE calibration_samples (id TEXT PRIMARY KEY, assay_id TEXT NOT NULL, device TEXT NOT NULL,
            created REAL NOT NULL, known_value REAL NOT NULL, features TEXT NOT NULL, note TEXT);
        CREATE TABLE models (assay_id TEXT NOT NULL, device TEXT NOT NULL, created REAL NOT NULL, kind TEXT NOT NULL,
            payload TEXT NOT NULL, metrics TEXT NOT NULL, PRIMARY KEY (assay_id, device));
        INSERT INTO calibration_samples VALUES ('s1', 'milk-starch-iodine', 'p', 0, 1, '3.5', '');
        INSERT INTO models VALUES ('milk-starch-iodine', 'p', 0, 'curve', '{}', '{"levels": 3}');
    """)
    con.commit()
    con.close()

    from sift.data.store import Store
    store = Store(db)
    assert store.get_model("milk-starch-iodine", "p")["metrics"] == {"levels": 3}
    assert [s["id"] for s in store.samples("milk-starch-iodine", "p")] == ["s1"]
    assert store.get_model("milk-starch-iodine", "p", owner="sift_abc") is None
    Store(db)  # second open is a no-op
