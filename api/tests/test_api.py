import struct

import cv2
import httpx
import numpy as np

from sift.agent.client import MetaClient
from tests.test_core import fake_scan, photo_of_card


def jpeg(img):
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tobytes()


def post_card(client, rgb=(45, 50, 110), headers=None, **form):
    data = {"assay_id": "milk-starch-iodine", "device": "test-phone"} | form
    return client.post("/v1/runs/card", data=data, headers=headers or {},
                       files={"image": ("c.jpg", jpeg(photo_of_card(rgb)), "image/jpeg")})


def test_health_reports_offline_agent(client):
    r = client.get("/health")
    assert r.json()["agent"] == "offline"
    assert r.headers["X-Content-Type-Options"] == "nosniff" and r.headers["X-Request-ID"]


def test_assays_list(client):
    ids = {a["id"]: a for a in client.get("/v1/assays").json()}
    assert ids["milk-starch-iodine"]["runnable"] is True
    assert ids["honey-pollen-origin"]["runnable"] is False


def test_card_run_end_to_end_and_truth(client):
    r = post_card(client)
    body = r.json()
    assert r.status_code == 200, body
    assert body["verdict"] == "flag" and body["report"]["agent"] == "offline"
    t = client.post(f"/v1/runs/{body['run_id']}/truth", json={"value": 1}).json()
    assert t["accuracy"]["n"] == 1


def test_validation_run_cannot_become_calibration_sample(client):
    run_id = post_card(client).json()["run_id"]
    client.post(f"/v1/runs/{run_id}/truth", json={"value": 1})
    r = client.post("/v1/calibration/samples", json={"run_id": run_id, "known_value": 1})
    assert r.status_code == 409


def test_planned_assay_not_runnable(client):
    frames = fake_scan(0, np.random.default_rng(0))
    r = client.post("/v1/runs/screenlight", json={"assay_id": "beef-pork-screenlight", "frames": frames})
    assert r.status_code == 409 and r.json()["error"]["code"] == "conflict"


def test_screenlight_without_model_asks_for_calibration(client):
    frames = fake_scan(10, np.random.default_rng(2))
    r = client.post("/v1/runs/screenlight", json={"assay_id": "olive-oil-screenlight", "frames": frames})
    assert r.json()["status"] == "needs_calibration"


def test_agent_offline_advances_step(client):
    r = client.post("/v1/agent/turn", json={"assay_id": "milk-starch-iodine", "step_id": "boil", "message": "done"})
    assert r.json()["step_id"] == "mix"


# ---- input guardrails --------------------------------------------------------------------

def test_non_image_upload_rejected(client):
    r = client.post("/v1/runs/card", data={"assay_id": "milk-starch-iodine"},
                    files={"image": ("x.jpg", b"<?php echo 1; ?>" * 100, "image/jpeg")})
    assert r.status_code == 422 and "JPEG" in r.json()["error"]["message"]


def test_oversize_upload_rejected(make_client):
    c = make_client(SIFT_MAX_IMAGE_BYTES=1000)
    assert post_card(c).status_code == 413


def test_bad_frames_rejected(client):
    frames = fake_scan(0, np.random.default_rng(0))
    frames["red"] = [[2.0, 0, 0]]
    r = client.post("/v1/runs/screenlight", json={"assay_id": "olive-oil-screenlight", "frames": frames})
    assert r.status_code == 422
    frames = fake_scan(0, np.random.default_rng(0))
    frames["ultraviolet"] = [[0.1, 0.1, 0.1]]
    r = client.post("/v1/runs/screenlight", json={"assay_id": "olive-oil-screenlight", "frames": frames})
    assert r.status_code == 422


def test_bad_assay_id_and_device_rejected(client):
    assert post_card(client, assay_id="../../etc").status_code == 422
    assert post_card(client, device="<script>").status_code == 422


def test_validation_errors_are_clean(client):
    r = client.post("/v1/agent/turn", json={"assay_id": "milk-starch-iodine"})
    err = r.json()["error"]
    assert r.status_code == 422 and err["code"] == "invalid_input" and err["request_id"]


# ---- auth, keys and rate limits --------------------------------------------------------------

def test_enterprise_tier_needs_key(client):
    assert post_card(client, tier="enterprise").status_code == 401


def test_admin_and_keys(make_client):
    c = make_client(SIFT_ADMIN_TOKEN="x" * 30)
    assert c.post("/v1/keys", json={"owner": "lab"}).status_code == 403
    assert c.post("/v1/keys", json={"owner": "lab"}, headers={"X-Admin-Token": "wrong"}).status_code == 403
    key = c.post("/v1/keys", json={"owner": "lab"}, headers={"X-Admin-Token": "x" * 30}).json()["key"]
    assert c.get("/v1/runs", headers={"X-Sift-Key": "sift_nope"}).status_code == 401

    keyed = post_card(c, headers={"X-Sift-Key": key}, tier="enterprise").json()["run_id"]
    public = post_card(c).json()["run_id"]
    # A keyed run is private to its key; public runs stay public.
    assert c.get(f"/v1/runs/{keyed}").status_code == 404
    assert c.get(f"/v1/runs/{keyed}", headers={"X-Sift-Key": key}).status_code == 200
    listed = {r["id"] for r in c.get("/v1/runs").json()}
    assert public in listed and keyed not in listed

    assert c.delete(f"/v1/keys/{key[:12]}", headers={"X-Admin-Token": "x" * 30}).status_code == 200
    assert c.get("/v1/runs", headers={"X-Sift-Key": key}).status_code == 401


def test_keys_stored_hashed(make_client, tmp_path):
    import sqlite3
    c = make_client(SIFT_ADMIN_TOKEN="y" * 30)
    key = c.post("/v1/keys", json={"owner": "lab"}, headers={"X-Admin-Token": "y" * 30}).json()["key"]
    rows = sqlite3.connect(tmp_path / "t.db").execute("SELECT key_hash, prefix FROM api_keys").fetchall()
    assert rows and all(key not in r[0] for r in rows)


def test_rate_limit(make_client):
    c = make_client(SIFT_RATE_PUBLIC=3)
    codes = [c.get("/v1/runs").status_code for _ in range(4)]
    assert codes[:3] == [200, 200, 200] and codes[3] == 429
    assert int(c.get("/v1/runs").headers["Retry-After"]) >= 1


def test_rate_limit_ignores_spoofed_xff_from_untrusted_peer(make_client):
    c = make_client(SIFT_RATE_PUBLIC=2, SIFT_TRUST_PROXY=1)
    # TestClient's peer ("testclient") is not the Docker proxy, so X-Forwarded-For is ignored
    # and rotating it per request still shares one bucket.
    assert c.get("/v1/runs", headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 200
    assert c.get("/v1/runs", headers={"X-Forwarded-For": "2.2.2.2"}).status_code == 200
    assert c.get("/v1/runs", headers={"X-Forwarded-For": "3.3.3.3"}).status_code == 429


def test_rate_limit_ignores_xff_when_trust_proxy_off(make_client):
    c = make_client(SIFT_RATE_PUBLIC=2)  # SIFT_TRUST_PROXY defaults to 0
    assert c.get("/v1/runs", headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 200
    assert c.get("/v1/runs", headers={"X-Forwarded-For": "2.2.2.2"}).status_code == 200
    assert c.get("/v1/runs", headers={"X-Forwarded-For": "3.3.3.3"}).status_code == 429


def test_client_ip_takes_last_entry_from_trusted_proxy():
    from types import SimpleNamespace

    from sift.http.deps import client_ip

    def ip(xff, peer, trust=True):
        headers = {"x-forwarded-for": xff} if xff else {}
        req = SimpleNamespace(headers=headers, client=SimpleNamespace(host=peer))
        c = SimpleNamespace(settings=SimpleNamespace(trust_proxy=trust))
        return client_ip(req, c)

    # Trusted Docker peer (nginx): nginx appends the real client last, so the last entry wins.
    assert ip("1.2.3.4", "172.18.0.3") == "1.2.3.4"
    assert ip("spoofed, 1.2.3.4", "172.18.0.3") == "1.2.3.4"
    assert ip("1.2.3.4, 1.2.3.4", "10.0.0.5") == "1.2.3.4"  # caddy + nginx both saw the client
    assert ip(None, "172.18.0.3") == "172.18.0.3"
    assert ip("  ", "172.18.0.3") == "172.18.0.3"
    # Untrusted peers (direct internet, LAN, test harness): X-Forwarded-For is ignored.
    assert ip("1.2.3.4", "203.0.113.5") == "203.0.113.5"
    assert ip("spoofed, 1.2.3.4", "192.168.1.10") == "192.168.1.10"
    assert ip("1.2.3.4", "testclient") == "testclient"
    # Trust off: always the immediate peer.
    assert ip("1.2.3.4", "172.18.0.3", trust=False) == "172.18.0.3"



def test_catalog_health_card_rate_limited(make_client):
    for path in ["/v1/assays", "/v1/assays/milk-starch-iodine", "/health", "/v1/card.svg"]:
        c = make_client(SIFT_RATE_CATALOG=3)
        codes = [c.get(path).status_code for _ in range(4)]
        assert codes == [200, 200, 200, 429], path


def test_catalog_browsing_does_not_use_up_the_run_budget(make_client):
    c = make_client(SIFT_RATE_PUBLIC=2)
    for _ in range(10):
        assert c.get("/v1/assays").status_code == 200
    assert c.get("/v1/runs").status_code == 200


def test_catalog_keyed_uses_keyed_limit(make_client):
    c = make_client(SIFT_RATE_CATALOG=1, SIFT_RATE_KEYED=5, SIFT_ADMIN_TOKEN="k" * 30)
    key = c.post("/v1/keys", json={"owner": "lab"}, headers={"X-Admin-Token": "k" * 30}).json()["key"]
    h = {"X-Sift-Key": key}
    assert c.get("/v1/assays").status_code == 200
    assert c.get("/v1/assays").status_code == 429
    for _ in range(5):
        assert c.get("/v1/assays", headers=h).status_code == 200
    assert c.get("/v1/assays", headers=h).status_code == 429


def test_oversize_json_rejected_before_parsing(make_client):
    c = make_client(SIFT_MAX_JSON_BYTES=1000)
    frames = fake_scan(0, np.random.default_rng(0))
    frames["white"] = [[0.5, 0.5, 0.5]] * 200
    r = c.post("/v1/runs/screenlight", json={"assay_id": "olive-oil-screenlight", "frames": frames})
    assert r.status_code == 413 and r.json()["error"]["code"] == "too_large"


def test_json_cap_ignores_multipart(make_client):
    c = make_client(SIFT_MAX_JSON_BYTES=1000)
    assert post_card(c).status_code == 200


def test_frames_schema_caps_before_assay_lookup(client):
    many_colours = {f"c{i}": [[0.1, 0.1, 0.1]] for i in range(33)}
    r = client.post("/v1/runs/screenlight", json={"assay_id": "no-such-assay", "frames": many_colours})
    assert r.status_code == 422
    many_frames = {"white": [[0.1, 0.1, 0.1]] * 61, "black": [[0.0, 0.0, 0.0]]}
    r = client.post("/v1/runs/screenlight", json={"assay_id": "no-such-assay", "frames": many_frames})
    assert r.status_code == 422


def test_agent_offline_matches_whole_words(client):
    def step_after(message, step="boil"):
        return client.post("/v1/agent/turn", json={"assay_id": "milk-starch-iodine", "step_id": step,
                                                   "message": message}).json()["step_id"]
    assert step_after("Done!") == "mix"
    assert step_after("okay") == "mix"
    assert step_after("I'm not done yet") == "boil"
    assert step_after("how long should I look at it?") == "boil"
    assert step_after("is the photograph next?") == "boil"
    assert step_after("go back", "mix") == "boil"
    assert step_after("retake", "mix") == "photo"


def test_agent_turn_checks_tier_and_runnable(client):
    r = client.post("/v1/agent/turn", json={"assay_id": "milk-starch-iodine", "message": "hi", "tier": "enterprise"})
    assert r.status_code == 401
    r = client.post("/v1/agent/turn", json={"assay_id": "honey-pollen-origin", "message": "hi"})
    assert r.status_code == 409


# ---- voice transcription ---------------------------------------------------------------------

def _wav_16k_mono():
    """Smallest WAV sniff_audio accepts: 44-byte header, mono 16-bit PCM at 16 kHz, no samples."""
    return struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36, b"WAVE", b"fmt ", 16, 1, 1, 16000, 32000, 2, 16,
                       b"data", 0)


def _keyed_client_with_meta(make_client, handler, **env):
    c = make_client(MODEL_API_KEY="test-key", **env)
    c.app.state.container.client = MetaClient(c.app.state.container.settings,
                                              transport=httpx.MockTransport(handler), retries=0, backoff=0)
    return c


def test_transcribe_without_key_is_unavailable(client):
    r = client.post("/v1/transcribe", files={"audio": ("voice.wav", _wav_16k_mono(), "audio/wav")})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "unavailable"


def test_transcribe_returns_text_and_agent(make_client):
    c = _keyed_client_with_meta(make_client, lambda req: httpx.Response(200, json={"transcript": "next step"}))
    r = c.post("/v1/transcribe", files={"audio": ("voice.wav", _wav_16k_mono(), "audio/wav")})
    assert r.status_code == 200, r.json()
    assert r.json() == {"text": "next step", "agent": "muse-voice"}


def test_transcribe_meta_outage_stays_unavailable(make_client):
    c = _keyed_client_with_meta(make_client, lambda req: httpx.Response(503, text="down"))
    r = c.post("/v1/transcribe", files={"audio": ("voice.wav", _wav_16k_mono(), "audio/wav")})
    assert r.status_code == 503
    assert "Type your message instead" in r.json()["error"]["message"]


def test_transcribe_rejects_non_wav(make_client):
    c = _keyed_client_with_meta(make_client, lambda req: httpx.Response(200, json={"transcript": "x"}))
    r = c.post("/v1/transcribe", files={"audio": ("voice.wav", b"not audio" * 100, "audio/wav")})
    assert r.status_code == 422


def test_vercel_entry_serves_the_app_under_api(monkeypatch, tmp_path):
    monkeypatch.setenv("SIFT_DB", str(tmp_path / "v.db"))
    from fastapi.testclient import TestClient

    from sift.vercel import app
    c = TestClient(app)
    assert c.get("/api/health").json()["ok"] is True
    assert c.get("/api/v1/foods").status_code == 200
    assert c.get("/api/docs").status_code == 200
    assert c.get("/v1/foods").status_code == 404
