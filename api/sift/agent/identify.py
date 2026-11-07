"""Point-and-know: which food profile a camera frame shows, via Muse vision.

The model picks a food id through the `identify_food` tool, never free text, so its
answer is always one of the loaded profiles or "unknown". Anything outside the
registry is discarded, and below 0.5 confidence the answer is "no verdict yet"
(food None) with the top candidates so the UI asks the user to pick.

Without MODEL_API_KEY, or when Meta is unreachable, this degrades to the offline
answer: no food, every profile as a candidate, clearly marked `agent: offline`.
"""

from __future__ import annotations

import logging
import math

from ..domain import foods
from . import guardrails as g
from .client import MetaClient, MetaUnavailable, image_part

log = logging.getLogger("sift.identify")

CONFIDENCE_MIN = 0.5
MAX_SEEN_CHARS = 200

SYSTEM = """You identify which food the user is pointing their phone camera at, so Sift can load \
the right food profile for a scan. Look at the frame and call the identify_food tool once.
Rules:
- food must be the closest profile id, or "unknown" when nothing fits or the frame is unclear.
- confidence is how sure you are the frame shows that food, 0 to 1. Below 0.5 the user picks.
- seen is one short sentence describing what you see: the item, its container, nothing else.
- Never promise the food is safe, pure or genuine; this only picks a profile, it is not a result.
"""


def _tool(food_ids: list[str]) -> dict:
    return {"type": "function", "function": {
        "name": "identify_food",
        "description": "Name the food profile the camera frame shows.",
        "parameters": {"type": "object", "properties": {
            "food": {"type": "string", "enum": [*food_ids, "unknown"],
                     "description": "Closest food profile id, or unknown"},
            "confidence": {"type": "number", "description": "0 to 1, how sure the frame shows that food"},
            "seen": {"type": "string", "description": "One short sentence describing the frame"}},
            "required": ["food", "confidence", "seen"]}}}


def _brief() -> str:
    lines = []
    for fid, f in sorted(foods.load_all().items()):
        aliases = ", ".join(str(a) for a in (f.get("aliases") or [])[:6])
        line = f"- {fid}: {f.get('name', fid)}"
        if aliases:
            line += f" (also called: {aliases})"
        lines.append(line)
    return "\n".join(lines)


def _clean_seen(raw: object) -> str:
    """Short user-facing description: no control characters, links or safety claims."""
    text = g.clean_user_text(str(raw or ""), MAX_SEEN_CHARS)
    return g.clean_reply(text, {"references": []})[:MAX_SEEN_CHARS].strip()


def _confidence(raw: object) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(value):
        return 0.0
    return min(1.0, max(0.0, value))


def identify(client: MetaClient, jpeg: bytes) -> dict:
    """Identify the food in `jpeg`. Always honest: unknown ids and low confidence
    come back as food None with candidates for the user to pick from."""
    ids = sorted(foods.load_all())
    offline = {"food": None, "confidence": 0.0, "seen": "", "candidates": ids, "agent": "offline"}
    if not client.online:
        return dict(offline)
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": [
            {"type": "text", "text": f"Food profiles:\n{_brief()}\nIdentify this frame with identify_food."},
            image_part(jpeg)]},
    ]
    try:
        args = client.call_tool(messages, _tool(ids))
    except MetaUnavailable as exc:
        log.warning("identify failed: %s", exc)
        return dict(offline)
    food = args.get("food")
    food_id = food if isinstance(food, str) and food in ids else None
    confidence = _confidence(args.get("confidence"))
    seen = _clean_seen(args.get("seen"))
    if food_id is None or confidence < CONFIDENCE_MIN:
        return {"food": None, "confidence": confidence, "seen": seen,
                "candidates": [food_id] if food_id else ids, "agent": "muse-spark"}
    return {"food": food_id, "confidence": confidence, "seen": seen,
            "candidates": [food_id], "agent": "muse-spark"}
