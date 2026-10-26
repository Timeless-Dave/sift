"""The Lab Agent. Muse Spark guides each protocol step, inspects captures and writes the
report; deterministic code does every measurement. The agent sees the numbers code produced
and is told not to change them.

Every function here works without a key: offline mode returns the protocol text and a
templated report, clearly marked `agent: offline`.
"""

from __future__ import annotations

import json
import logging

from . import registry
from .meta_client import MetaClient, MetaUnavailable, image_part

log = logging.getLogger("sift.agent")

SYSTEM = """You are the Sift Lab Agent, a careful food-testing lab partner working through a phone.
Rules:
- Guide one protocol step at a time, in plain words, at most 3 short sentences.
- Never invent measurements. Numbers, verdicts and confidence come only from the tool results you are given.
- A Sift result is a screening result. Always say which lab method would confirm it.
- If a capture is poor, say exactly what to fix.
- For the public tier, avoid jargon. For the research tier, you may use technical terms and cite the method paper.
"""

AGENT_TOOLS = [
    {"type": "function", "function": {
        "name": "go_to_step",
        "description": "Move the user to a protocol step (use when they finish a step, ask to go back, or ask to retake).",
        "parameters": {"type": "object", "properties": {
            "step_id": {"type": "string", "description": "Protocol step id"},
            "reason": {"type": "string"}}, "required": ["step_id"]}}},
    {"type": "function", "function": {
        "name": "open_camera",
        "description": "Ask the app to open the capture screen for the assay's capture step.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "start_timer",
        "description": "Start a countdown for a waiting step.",
        "parameters": {"type": "object", "properties": {"seconds": {"type": "integer"}},
                       "required": ["seconds"]}}},
]

CAPTURE_TOOL = {"type": "function", "function": {
    "name": "capture_review",
    "description": "Report what is visible in the rectified reference-card image.",
    "parameters": {"type": "object", "properties": {
        "sample_visible": {"type": "boolean", "description": "Is a sample inside the ring?"},
        "matches_expected": {"type": "boolean",
                             "description": "Does the sample look like the expected material for this step?"},
        "issues": {"type": "array", "items": {"type": "string"},
                   "description": "Concrete problems: shadows, fingers, spill outside ring, wrong item, bubbles."},
        "advice": {"type": "string", "description": "One sentence telling the user what to do next."}},
        "required": ["sample_visible", "matches_expected", "issues", "advice"]}}}


def _assay_brief(assay: dict) -> str:
    steps = "\n".join(f"- [{s['id']}] {s['title']}: {s['instruction']}" for s in assay.get("protocol", []))
    refs = "; ".join(r["title"] for r in assay.get("references", []))
    return (f"Assay: {assay['name']} ({assay['id']}). Food: {assay['food']}. Question: {assay.get('question','')}\n"
            f"Method: {assay['method']}. Confirm with: {assay.get('confirm_with','')}\n"
            f"Protocol:\n{steps}\nSources: {refs}")


class LabAgent:
    def __init__(self, client: MetaClient):
        self.client = client

    # Guided conversation -------------------------------------------------------------
    def turn(self, assay_id: str, step_id: str | None, history: list[dict], user_text: str, tier: str) -> dict:
        assay = registry.get(assay_id)
        steps = assay["protocol"]
        current = next((s for s in steps if s["id"] == step_id), steps[0])
        if not self.client.online:
            return self._offline_turn(assay, current, user_text)

        messages = [{"role": "system", "content": SYSTEM},
                    {"role": "system", "content": f"Tier: {tier}\n{_assay_brief(assay)}\nCurrent step: {current['id']}"}]
        messages += [m for m in history[-12:] if m.get("role") in ("user", "assistant") and m.get("content")]
        messages.append({"role": "user", "content": user_text})
        try:
            msg = self.client.chat(messages, tools=AGENT_TOOLS)
        except MetaUnavailable as exc:
            log.warning("agent turn failed: %s", exc)
            out = self._offline_turn(assay, current, user_text)
            out["agent_error"] = str(exc)
            return out

        actions, next_step = [], current["id"]
        for call in msg.get("tool_calls") or []:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            if name == "go_to_step" and any(s["id"] == args.get("step_id") for s in steps):
                next_step = args["step_id"]
            actions.append({"name": name, "args": args})
        text = (msg.get("content") or "").strip()
        if not text:
            target = next(s for s in steps if s["id"] == next_step)
            text = target["instruction"]
        return {"agent": "muse-spark", "reply": text, "step_id": next_step, "actions": actions}

    def _offline_turn(self, assay: dict, current: dict, user_text: str) -> dict:
        steps = assay["protocol"]
        idx = steps.index(current)
        words = user_text.lower()
        actions = []
        if any(w in words for w in ("next", "done", "ready", "finished", "ok")) and idx + 1 < len(steps):
            current = steps[idx + 1]
        elif any(w in words for w in ("back", "previous")) and idx > 0:
            current = steps[idx - 1]
        elif any(w in words for w in ("retake", "again", "photo", "scan")):
            current = registry.capture_step(assay)
            actions.append({"name": "open_camera", "args": {}})
        if current.get("wait_seconds"):
            actions.append({"name": "start_timer", "args": {"seconds": current["wait_seconds"]}})
        return {"agent": "offline", "reply": current["instruction"], "step_id": current["id"], "actions": actions}

    # Capture review -----------------------------------------------------------------
    def review_capture(self, assay: dict, warped_jpeg: bytes) -> dict | None:
        if not self.client.online:
            return None
        step = registry.capture_step(assay)
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": [
                {"type": "text", "text": f"{_assay_brief(assay)}\nThis is the rectified reference card for step "
                                         f"'{step['title']}'. Review it with the capture_review tool."},
                image_part(warped_jpeg)]},
        ]
        try:
            return self.client.call_tool(messages, CAPTURE_TOOL)
        except (MetaUnavailable, json.JSONDecodeError) as exc:
            log.warning("capture review failed: %s", exc)
            return None

    # Report ---------------------------------------------------------------------------
    def write_report(self, assay: dict, result: dict, tier: str) -> dict:
        facts = {k: result.get(k) for k in ("status", "mode", "label", "verdict", "value", "unit",
                                             "confidence", "in_range", "rule")}
        facts["quality"] = result.get("quality", {}).get("metrics")
        facts["model"] = result.get("model")
        template = self._template_report(assay, result)
        if not self.client.online or result.get("status") != "ok":
            return {"agent": "offline", "text": template}
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": (
                f"Tier: {tier}\n{_assay_brief(assay)}\nMeasured result (from code, do not change): "
                f"{json.dumps(facts)}\nWrite the result for this user in at most 4 sentences: what was found, "
                "how confident Sift is and why, and what lab method would confirm it.")},
        ]
        try:
            msg = self.client.chat(messages, max_tokens=300)
            text = (msg.get("content") or "").strip() or template
            return {"agent": "muse-spark", "text": text}
        except MetaUnavailable as exc:
            log.warning("report failed: %s", exc)
            return {"agent": "offline", "text": template, "agent_error": str(exc)}

    @staticmethod
    def _template_report(assay: dict, result: dict) -> str:
        if result.get("status") == "rejected":
            fixes = " ".join(p["fix"] for p in result["quality"]["problems"] if p["severity"] == "reject")
            return f"This capture couldn't be read. {fixes}"
        if result.get("status") == "needs_calibration":
            return f"{result['label']} {result['next_step']}"
        value = f" ({result['value']} {result['unit']})" if result.get("value") is not None else ""
        basis = ("Based on a calibration curve for this phone." if result.get("mode") == "calibrated"
                 else "This is a present-or-absent reading from the colour rule; it does not measure how much.")
        return f"{result['label']}{value}. Confidence {round(result['confidence'] * 100)}%. {basis}"
