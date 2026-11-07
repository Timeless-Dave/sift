"""SAM 3.1 over the Responses API: documented request/response shape plus malformed fallbacks.

One-bit vectors were produced by the reference meta-sam-parser encoder; the lossless
vector is a captured API payload with its expected raster from the conformance suite.
"""
import base64
import json

import httpx
import numpy as np
import pytest

from sift.agent import sam
from sift.agent.client import MetaClient, MetaUnavailable
from sift.core.config import Settings

RING_ROWS = ["00111100", "01111110", "01100110", "01100110", "01111110", "00111100"]
RING_8X6 = bytes(int(c) for row in RING_ROWS for c in row)
RING_8X6_PAYLOAD = "!!!!!-L9p^xMrd3_TuU"
CHECKER_5X5 = bytes((x + y) % 2 == 0 for y in range(5) for x in range(5))
CHECKER_5X5_PAYLOAD = "!!!!!'^%C^ipY"
ONES_4X4_PAYLOAD = "!!!!!'y80v-)c"
LOSSLESS_11X11_PAYLOAD = ("~!!!!r!kCq#$.pF[_cZIw.?wO3R8-&NJofiCI$_J0aA.1VC*YyK_'z*(LEG8!+H9evY.82Z-4.@C[."
                          "9C@T86o$3E=-&8w3W=]xS.")
LOSSLESS_11X11_RUNS = [(0, 4), (1, 2), (0, 7), (1, 7), (0, 3), (1, 9), (0, 2), (1, 9), (0, 1), (1, 22),
                       (0, 1), (1, 10), (0, 1), (1, 10), (0, 1), (1, 9), (0, 3), (1, 8), (0, 5),
                       (1, 3), (0, 4)]
LOSSLESS_11X11 = bytes(v for v, n in LOSSLESS_11X11_RUNS for _ in range(n))

JPEG = b"\xff\xd8fake-jpeg-bytes\xff\xd9"
PROMPT = "circle"


def _envelope(text):
    return {"id": "resp_test", "object": "response", "status": "completed",
            "output": [{"type": "message", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": text, "annotations": []}]}]}


def _record(object_id, payload, width, height, source=None, at=(0, 0), confidence=None):
    """A record whose box is exactly the mask raster, placed at `at` in a `source` (w, h) frame."""
    fw, fh = source or (width, height)
    x1, y1 = at
    box = f"x1={x1};y1={y1};x2={x1 + width - 1};y2={y1 + height - 1};w={fw};h={fh}"
    mask = f"x=0;y=0;data={height},{width},{payload}"
    if confidence is not None:
        box += f";c={confidence}"
        mask += f";c={confidence}"
    return f"{object_id}<|box;{box}|><|mask;{mask}|>"


def _client(handler, **settings) -> MetaClient:
    s = Settings(meta_api_key="test-key", **settings)
    return MetaClient(s, transport=httpx.MockTransport(handler), retries=0, backoff=0)


def test_segment_posts_documented_responses_request():
    line = f"<0f>{_record(0, RING_8X6_PAYLOAD, 8, 6)}"

    def handler(request):
        assert request.url.path == "/v1/responses"
        body = json.loads(request.content)
        assert body["model"] == "sam-3.1"
        content = body["input"][0]["content"]
        assert body["input"][0]["role"] == "user"
        assert content[0] == {"type": "input_text", "text": PROMPT}
        assert content[1]["type"] == "input_image"
        assert content[1]["image_url"] == "data:image/jpeg;base64," + base64.b64encode(JPEG).decode()
        assert body["metadata"] == {"mask_encoding": "one_bit"}
        assert body["stream"] is False
        return httpx.Response(200, json=_envelope(line))

    [mask] = _client(handler).segment(JPEG, PROMPT, (6, 8))
    assert mask.dtype == bool and mask.shape == (6, 8)
    assert mask.tolist() == [[bool(int(c)) for c in row] for row in RING_ROWS]


def test_segment_places_box_sized_mask_in_frame():
    # As the live API returns: the mask raster is the size of its box, not of the frame.
    line = ("<0f>0<|box;x1=513;y1=371;x2=523;y2=381;w=1440;h=900|>"
            f"<|mask;x=0;y=0;data=11,11,{LOSSLESS_11X11_PAYLOAD}|>")
    c = _client(lambda request: httpx.Response(200, json=_envelope(line)))
    [mask] = c.segment(JPEG, PROMPT, (900, 1440))
    expected = np.frombuffer(LOSSLESS_11X11, dtype=np.uint8).astype(bool).reshape(11, 11)
    assert (mask[371:382, 513:524] == expected).all()
    assert mask.sum() == expected.sum()  # nothing outside the box


def test_segment_returns_every_match():
    line = (f"<0f>{_record(0, RING_8X6_PAYLOAD, 8, 6, source=(20, 20), confidence=0.91)},"
            f"{_record(2, CHECKER_5X5_PAYLOAD, 5, 5, source=(20, 20), at=(10, 10), confidence=0.87)}\n")
    c = _client(lambda request: httpx.Response(200, json=_envelope(line)))
    ring, checker = c.segment(JPEG, PROMPT, (20, 20))
    assert ring[:6, :8].tolist() == [[bool(int(c)) for c in row] for row in RING_ROWS] and not ring[6:].any()
    assert checker[10:15, 10:15].sum() == sum(CHECKER_5X5) and not checker[:10].any()


def test_segment_resizes_to_shape():
    line = f"<0f>{_record(0, ONES_4X4_PAYLOAD, 4, 4)}"
    c = _client(lambda request: httpx.Response(200, json=_envelope(line)))
    [mask] = c.segment(JPEG, PROMPT, (8, 8))
    assert mask.dtype == bool and mask.shape == (8, 8) and mask.all()


def _bad_response(kind):
    if kind == "http-500":
        return httpx.Response(500, text="down")
    if kind == "not-json":
        return httpx.Response(200, text="ok")
    if kind == "not-a-dict":
        return httpx.Response(200, json=[1, 2])
    if kind == "failed-status":
        return httpx.Response(200, json={"status": "failed", "output": []})
    if kind == "missing-output":
        return httpx.Response(200, json={"status": "completed"})
    if kind == "empty-output":
        return httpx.Response(200, json={"status": "completed", "output": []})
    texts = {
        "empty-lane": "",
        "blank-lane": "   \n ",
        "garbage": "here is your mask: none",
        "bare-header": "<0f>",
        "no-tokens": "<0f>0",
        "bad-marker": f"<0f>{_record(0, '*' + RING_8X6_PAYLOAD[1:], 8, 6)}",
        "truncated-payload": f"<0f>{_record(0, RING_8X6_PAYLOAD[:-6], 8, 6)}",
        "corrupt-payload": f"<0f>{_record(0, RING_8X6_PAYLOAD[:-2] + 'AB', 8, 6)}",
        "box-outside-frame": "<0f>0<|box;x1=2;y1=3;x2=400;y2=50;w=100;h=100|>"
                             f"<|mask;x=0;y=0;data=6,8,{RING_8X6_PAYLOAD}|>",
        "zero-mask-dim": f"<0f>{_record(0, RING_8X6_PAYLOAD, 8, 6)}".replace("data=6,8,", "data=0,8,"),
    }
    return httpx.Response(200, json=_envelope(texts[kind]))


@pytest.mark.parametrize("kind", ["http-500", "not-json", "not-a-dict", "failed-status", "missing-output",
                                  "empty-output", "empty-lane", "blank-lane", "garbage", "bare-header",
                                  "no-tokens", "bad-marker", "truncated-payload", "corrupt-payload",
                                  "box-outside-frame", "zero-mask-dim"])
def test_segment_failures_raise_meta_unavailable(kind):
    c = _client(lambda request: _bad_response(kind))
    with pytest.raises(MetaUnavailable):
        c.segment(JPEG, PROMPT, (6, 8))


def test_sam_path_defaults_to_responses(monkeypatch):
    monkeypatch.delenv("SIFT_SAM_PATH", raising=False)
    assert Settings().sam_path == "/responses"


def test_segment_uses_configured_path():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        return httpx.Response(200, json=_envelope(f"<0f>{_record(0, ONES_4X4_PAYLOAD, 4, 4)}"))

    _client(handler, sam_path="/custom").segment(JPEG, PROMPT, (4, 4))
    assert seen["path"] == "/v1/custom"


def test_parse_tolerates_documented_variants():
    line = ("<0f;note=1>,2<|mask;x=0;y=0;data=5,5," + CHECKER_5X5_PAYLOAD + "|>"
            "<|box;x1=1;y1=1;x2=9;y2=9;w=10;h=10;c=0.5|><|future;v=1|>,"
            "7<|box;x1=0;y1=0;x2=1;y2=1;w=10;h=10;zzz=9|><|mask;x=0;y=0;data=5,5,"
            + CHECKER_5X5_PAYLOAD + "|>")
    records = sam.parse_output_text(line + "\n")
    assert [(r.frame, r.object_id) for r in records] == [(0, 2), (0, 7)]
    assert records[0].box == (1, 1, 9, 9, 10, 10)
    assert records[0].mask.encoding == "one_bit"
    assert sam.decode_mask(records[1].mask) == CHECKER_5X5


@pytest.mark.parametrize("text", ["", "   ", "<0f>", "<0f>,", "<0f>0",
                                  "<0f>0<|box;x1=0;y1=0;x2=1;y2=1;w=10;h=10|>",
                                  "<0f>0<|mask;x=0;y=0;data=5,5," + CHECKER_5X5_PAYLOAD + "|>",
                                  "<0f>x<|box;x1=0;y1=0;x2=1;y2=1;w=10;h=10|>"
                                  "<|mask;x=0;y=0;data=5,5," + CHECKER_5X5_PAYLOAD + "|>",
                                  "<0f>0<|box;x1=0;y1=0;x2=1;y2=1;x2=2;w=10;h=10|>"
                                  "<|mask;x=0;y=0;data=5,5," + CHECKER_5X5_PAYLOAD + "|>",
                                  "not a line\n<0f>0<|box;x1=0;y1=0;x2=1;y2=1;w=10;h=10|>"
                                  "<|mask;x=0;y=0;data=5,5," + CHECKER_5X5_PAYLOAD + "|>"])
def test_parse_rejects_malformed_lines(text):
    with pytest.raises(ValueError):
        sam.parse_output_text(text)


def test_decode_mask_rejects_bad_sizes():
    with pytest.raises(ValueError):
        sam.decode_mask(sam.SamMask("one_bit", RING_8X6_PAYLOAD, 0, 6))
    with pytest.raises(ValueError):
        sam.decode_mask(sam.SamMask("one_bit", RING_8X6_PAYLOAD, 2000, 2000))
    with pytest.raises(ValueError):
        sam.decode_mask(sam.SamMask("one_bit", "?" + RING_8X6_PAYLOAD[1:], 8, 6))


# ---- choosing the sample among SAM's matches --------------------------------------------------

def test_pick_sam_mask_ignores_ring_and_strays():
    from sift.vision.colorimetric import pick_sam_mask
    yy, xx = np.mgrid[0:100, 0:100]
    circle = (xx - 50) ** 2 + (yy - 50) ** 2 <= 30 ** 2
    sample = (xx - 50) ** 2 + (yy - 50) ** 2 <= 15 ** 2
    ring = ((xx - 50) ** 2 + (yy - 50) ** 2 <= 40 ** 2) & ~sample
    stray = np.zeros_like(circle)
    stray[:5, :5] = True
    assert pick_sam_mask([ring, stray, sample], circle) is sample
    assert pick_sam_mask([ring, stray], circle) is None


def test_analyze_uses_sam_sample_not_ring():
    from sift.domain import registry
    from sift.vision import card, colorimetric
    from tests.test_core import photo_of_card
    img = photo_of_card((45, 50, 110))
    warped = card.detect_and_rectify(img)
    h, w = warped.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    cx, cy = 60 * 8, 55 * 8
    sample = (xx - cx) ** 2 + (yy - cy) ** 2 <= (6 * 8) ** 2
    ring = (xx - cx) ** 2 + (yy - cy) ** 2 <= (15 * 8) ** 2
    res = colorimetric.analyze(img, registry.get("milk-starch-iodine"), None, [ring, sample])
    assert res["segmentation"] == "sam-3.1" and res["verdict"] == "flag"
    res = colorimetric.analyze(img, registry.get("milk-starch-iodine"), None, [ring])
    assert res["segmentation"] == "card-window"
