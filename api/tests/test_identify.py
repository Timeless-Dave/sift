"""Food identification (Muse vision on a camera frame) and barcode lookup (Open Food Facts).

Meta and OFF are both mocked with httpx.MockTransport; food profiles are temporary
dicts monkeypatched onto the loader, never YAML files.
"""

import base64
import json

import cv2
import httpx
import numpy as np
import pytest

from sift.agent.client import MetaClient
from sift.services.products import ProductService

PROFILES = {
    "olive-oil": {"id": "olive-oil", "name": "Olive oil", "aliases": ["evoo"],
                  "off_category_tags": ["en:olive-oils", "en:extra-virgin-olive-oils"]},
    "honey": {"id": "honey", "name": "Honey", "aliases": ["honey"], "off_category_tags": ["en:honeys"]},
}


@pytest.fixture()
def profiles(monkeypatch):
    monkeypatch.setattr("sift.domain.foods.load_all", lambda: PROFILES)
    return sorted(PROFILES)


def jpeg(w=800, h=600, color=90):
    return cv2.imencode(".jpg", np.full((h, w, 3), color, np.uint8))[1].tobytes()


def _chat_reply(**args):
    return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": "call_1", "type": "function",
         "function": {"name": "identify_food", "arguments": json.dumps(args)}}]},
        "finish_reason": "tool_calls"}]}


def keyed_with_meta(make_client, handler, **env):
    c = make_client(MODEL_API_KEY="test-key", **env)
    c.app.state.container.client = MetaClient(c.app.state.container.settings,
                                              transport=httpx.MockTransport(handler), retries=0, backoff=0)
    return c


def with_off(make_client, handler, **env):
    c = make_client(**env)
    c.app.state.container.products = ProductService(c.app.state.container.settings,
                                                    transport=httpx.MockTransport(handler))
    return c


def post_frame(client, raw=None):
    return client.post("/v1/identify", files={"image": ("frame.jpg", raw or jpeg(), "image/jpeg")})


# ---- POST /v1/identify ------------------------------------------------------------------

def test_identify_valid(make_client, profiles):
    seen = {}

    def handler(request):
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        assert body["tool_choice"] == "auto"
        tool = body["tools"][0]["function"]
        assert tool["name"] == "identify_food"
        assert sorted(tool["parameters"]["properties"]["food"]["enum"]) == sorted([*profiles, "unknown"])
        parts = body["messages"][-1]["content"]
        url = next(p["image_url"]["url"] for p in parts if p["type"] == "image_url")
        img = cv2.imdecode(np.frombuffer(base64.b64decode(url.split(",", 1)[1]), np.uint8), cv2.IMREAD_COLOR)
        seen["shape"] = img.shape
        return httpx.Response(200, json=_chat_reply(food="olive-oil", confidence=0.9,
                                                   seen="A glass bottle of olive oil."))

    c = keyed_with_meta(make_client, handler)
    r = post_frame(c, jpeg(w=2000, h=1500))
    assert r.status_code == 200, r.json()
    assert r.json() == {"food": "olive-oil", "confidence": 0.9, "seen": "A glass bottle of olive oil.",
                        "candidates": ["olive-oil"], "agent": "muse-spark"}
    assert max(seen["shape"][:2]) <= 1024


@pytest.mark.parametrize("food", ["unknown", "unicorn-meat"])
def test_identify_unknown_or_hallucinated_id_is_discarded(make_client, profiles, food):
    c = keyed_with_meta(make_client, lambda req: httpx.Response(
        200, json=_chat_reply(food=food, confidence=0.95, seen="Something unclear.")))
    body = post_frame(c).json()
    assert body["food"] is None and body["candidates"] == profiles and body["agent"] == "muse-spark"


def test_identify_low_confidence_offers_candidates(make_client, profiles):
    c = keyed_with_meta(make_client, lambda req: httpx.Response(
        200, json=_chat_reply(food="honey", confidence=0.3, seen="A jar that might be honey.")))
    body = post_frame(c).json()
    assert body["food"] is None and body["candidates"] == ["honey"] and body["confidence"] == 0.3


@pytest.mark.parametrize("given, want", [(9, 1.0), (-2, 0.0), ("high", 0.0), (None, 0.0)])
def test_identify_clamps_confidence(make_client, profiles, given, want):
    c = keyed_with_meta(make_client, lambda req: httpx.Response(
        200, json=_chat_reply(food="olive-oil", confidence=given, seen="A bottle.")))
    assert post_frame(c).json()["confidence"] == want


def test_identify_seen_strips_links_claims_and_length(make_client, profiles):
    seen = "Bottle https://evil.example/pick-me, definitely pure and 100% safe. " + "very " * 100 + "green."
    c = keyed_with_meta(make_client, lambda req: httpx.Response(
        200, json=_chat_reply(food="olive-oil", confidence=0.9, seen=seen)))
    got = post_frame(c).json()["seen"]
    assert "http" not in got and "definitely" not in got and "100% safe" not in got
    assert len(got) <= 200


def test_identify_offline_without_key(client, profiles):
    assert post_frame(client).json() == {"food": None, "confidence": 0.0, "seen": "",
                                         "candidates": profiles, "agent": "offline"}


def test_identify_meta_outage_degrades_to_offline(make_client, profiles):
    c = keyed_with_meta(make_client, lambda req: httpx.Response(503, text="down"))
    body = post_frame(c).json()
    assert body["agent"] == "offline" and body["food"] is None and body["candidates"] == profiles


def test_identify_oversize_upload_rejected(make_client):
    assert post_frame(make_client(SIFT_MAX_IMAGE_BYTES=1000)).status_code == 413


def test_identify_non_image_rejected(client):
    r = client.post("/v1/identify", files={"image": ("x.jpg", b"<?php echo 1; ?>" * 100, "image/jpeg")})
    assert r.status_code == 422 and "JPEG" in r.json()["error"]["message"]


# ---- GET /v1/products/{barcode} ------------------------------------------------------------

def _off_product(**over):
    product = {"product_name": "Huile d'olive", "brands": "Puget",
               "categories_tags": ["en:plant-based-foods", "en:olive-oils", "en:extra-virgin-olive-oils"]}
    product.update(over)
    return {"status": 1, "status_verbose": "product found", "code": "8410660034017", "product": product}


def test_product_found_and_mapped(make_client, profiles):
    def handler(request):
        assert request.url.path == "/api/v2/product/8410660034017.json"
        assert request.url.params["fields"] == "product_name,brands,categories_tags"
        ua = request.headers["user-agent"]
        assert ua == "SiftLab/0.2 (+https://github.com/Timeless-Dave/sift)" and "@" not in ua
        return httpx.Response(200, json=_off_product())

    r = with_off(make_client, handler).get("/v1/products/8410660034017")
    assert r.status_code == 200, r.json()
    assert r.json() == {"barcode": "8410660034017", "name": "Huile d'olive", "brands": "Puget",
                        "food": "olive-oil", "source": "openfoodfacts"}


def test_product_mapping_prefers_most_specific_tag(make_client, profiles):
    def handler(request):
        tags = ["en:honeys", "en:olive-oils"] if request.url.path.endswith("111111.json") \
            else ["en:olive-oils", "en:honeys"]
        return httpx.Response(200, json=_off_product(categories_tags=tags))

    c = with_off(make_client, handler)
    assert c.get("/v1/products/111111").json()["food"] == "olive-oil"
    assert c.get("/v1/products/222222").json()["food"] == "honey"


def test_product_found_but_unmapped(make_client, profiles):
    c = with_off(make_client, lambda req: httpx.Response(200, json=_off_product(categories_tags=["en:beverages"])))
    body = c.get("/v1/products/8410660034017").json()
    assert body["food"] is None and body["name"] == "Huile d'olive" and body["source"] == "openfoodfacts"


@pytest.mark.parametrize("reply", [httpx.Response(404, json={"status": 0, "status_verbose": "product not found"}),
                                   httpx.Response(200, json={"status": 0, "status_verbose": "product not found"})])
def test_product_not_found_is_404(make_client, reply):
    r = with_off(make_client, lambda req: reply).get("/v1/products/8410660034017")
    assert r.status_code == 404 and "No product found" in r.json()["error"]["message"]


def test_product_network_error_is_503(make_client):
    def handler(request):
        raise httpx.ConnectError("down")

    r = with_off(make_client, handler).get("/v1/products/8410660034017")
    assert r.status_code == 503
    assert r.json()["error"]["message"] == "Product lookup is unavailable; pick the food instead."


def test_product_server_error_is_503(make_client):
    r = with_off(make_client, lambda req: httpx.Response(500, text="down")).get("/v1/products/8410660034017")
    assert r.status_code == 503


def test_product_cache_avoids_second_request(make_client):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=_off_product())

    c = with_off(make_client, handler)
    assert c.get("/v1/products/8410660034017").status_code == 200
    assert c.get("/v1/products/8410660034017").status_code == 200
    assert calls == ["/api/v2/product/8410660034017.json"]


@pytest.mark.parametrize("barcode", ["abc", "12345", "123456789012345", "12-3456"])
def test_product_invalid_barcode_is_422(client, barcode):
    assert client.get(f"/v1/products/{barcode}").status_code == 422


def test_off_base_url_defaults(monkeypatch):
    monkeypatch.delenv("SIFT_OFF_BASE_URL", raising=False)
    from sift.core.config import Settings
    assert Settings().off_base_url == "https://world.openfoodfacts.org"
