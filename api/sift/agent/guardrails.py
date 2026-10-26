"""Guardrails on everything the language model reads and writes.

Sift's rule is that code measures and the model explains. These checks enforce it:
the model can't introduce a number, contradict the measured verdict, promise safety,
or steer the user to a step that doesn't exist. Anything that fails falls back to the
deterministic template, and the response records why.
"""

from __future__ import annotations

import contextlib
import re
import unicodedata
from dataclasses import dataclass, field

MAX_REPORT_CHARS = 900
MAX_REPLY_CHARS = 600
MAX_ISSUES = 5
MAX_ISSUE_CHARS = 160
MAX_TIMER_SECONDS = 900

# Claims a screening test can never support.
BANNED = [
    r"\bsafe to (eat|drink|consume|use)\b",
    r"\b(completely|totally|100\s?%) (safe|pure|clean|natural)\b",
    r"\bguarantee[sd]?\b",
    r"\bcertif(y|ied|ies)\b",
    r"\blab[- ]grade\b",
    r"\bdiagnos(e|is|ed)\b",
    r"\bdefinitely\b",
    r"\bno need to (test|check|confirm)\b",
]
_BANNED_RE = re.compile("|".join(BANNED), re.IGNORECASE)
_NEGATION = re.compile(r"\b(no|not|none|nothing|without|n't)\b", re.IGNORECASE)
_DETECTION = re.compile(r"\b(detected|found|present|contains?|adulterated|mixed with|sign|evidence)\b",
                        re.IGNORECASE)
_CLEAN_WORDS = re.compile(r"\b(pure|clean|unadulterated|genuine)\b", re.IGNORECASE)
_SENTENCES = re.compile(r"(?<=[.!?;:])\s+")


def _claims(text: str) -> tuple[bool, bool]:
    """(says something was found, says nothing was found), judged sentence by sentence."""
    positive = negative = False
    for sentence in _SENTENCES.split(text):
        detection = bool(_DETECTION.search(sentence))
        negated = bool(_NEGATION.search(sentence))
        if (detection and negated) or _CLEAN_WORDS.search(sentence):
            negative = True
        elif detection:
            positive = True
    return positive, negative
_NUMBER_RE = re.compile(r"(?<![\w.])-?\d+(?:[.,]\d+)?")
_URL_RE = re.compile(r"https?://\S+")


@dataclass
class Verdict:
    ok: bool = True
    reasons: list[str] = field(default_factory=list)

    def fail(self, reason: str) -> None:
        self.ok = False
        self.reasons.append(reason)


def clean_user_text(text: str, limit: int) -> str:
    """Normalise and cap what users send to the model. Control and format characters
    (including zero-width and bidi overrides used to hide instructions) are removed."""
    text = unicodedata.normalize("NFKC", text or "")
    text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
    return text.strip()[:limit]


def _numbers(text: str) -> list[float]:
    out = []
    for m in _NUMBER_RE.findall(text):
        with contextlib.suppress(ValueError):
            out.append(float(m.replace(",", ".")))
    return out


def allowed_numbers(facts: dict, assay: dict) -> set[float]:
    """Every number the report may mention: the measured ones and those in the assay text."""
    allowed: set[float] = set()
    for key in ("value", "confidence"):
        v = facts.get(key)
        if isinstance(v, (int, float)):
            allowed.update({float(v), round(float(v), 1), round(float(v), 2), float(round(v))})
            if key == "confidence":
                allowed.update({round(v * 100), round(v * 100, 1)})
    for metric in (facts.get("quality") or {}).values():
        if isinstance(metric, (int, float)):
            allowed.add(round(float(metric), 2))
    for metric in (facts.get("model") or {}).values():
        if isinstance(metric, (int, float)):
            allowed.add(float(metric))
    text = " ".join(str(assay.get(k, "")) for k in ("name", "food", "question", "confirm_with", "summary"))
    text += " " + str((assay.get("analysis") or {}).get("unit", ""))
    text += " " + " ".join(f"{r.get('title','')} {r.get('source','')}" for r in assay.get("references", []))
    allowed.update(_numbers(text))
    return allowed


def check_report(text: str, facts: dict, assay: dict) -> Verdict:
    v = Verdict()
    if not text or not text.strip():
        v.fail("empty")
        return v
    if len(text) > MAX_REPORT_CHARS:
        v.fail("too_long")
    if _BANNED_RE.search(text):
        v.fail("unsupported_safety_claim")
    if _URL_RE.search(text):
        v.fail("link_in_report")
    allowed = allowed_numbers(facts, assay)
    stray = [n for n in _numbers(text) if not any(abs(n - a) <= 0.051 for a in allowed)]
    if stray:
        v.fail(f"number_not_measured:{stray[:3]}")
    verdict = facts.get("verdict")
    positive, negative = _claims(text)
    if verdict == "flag" and negative and not positive:
        v.fail("contradicts_flag")
    if verdict == "pass" and positive:
        v.fail("contradicts_pass")
    return v


def clean_reply(text: str, assay: dict) -> str:
    """Agent chat replies: cap length and drop links that aren't the assay's own sources."""
    allowed_urls = {r.get("url") for r in assay.get("references", [])}
    text = _URL_RE.sub(lambda m: m.group(0) if m.group(0).rstrip(").,") in allowed_urls else "", text or "")
    text = _BANNED_RE.sub("", text)
    return text.strip()[:MAX_REPLY_CHARS]


def clean_actions(raw_calls: list[dict], valid_steps: set[str]) -> tuple[list[dict], str | None]:
    """Keep only well-formed tool calls the app knows how to perform."""
    actions: list[dict] = []
    next_step: str | None = None
    for name, args in raw_calls[:4]:
        if name == "go_to_step":
            step = args.get("step_id")
            if isinstance(step, str) and step in valid_steps:
                next_step = step
                actions.append({"name": name, "args": {"step_id": step}})
        elif name == "open_camera":
            actions.append({"name": name, "args": {}})
        elif name == "start_timer":
            secs = args.get("seconds")
            if isinstance(secs, int) and 1 <= secs <= MAX_TIMER_SECONDS:
                actions.append({"name": name, "args": {"seconds": secs}})
    return actions, next_step


def clean_capture_review(review: dict) -> dict | None:
    try:
        issues = [str(i)[:MAX_ISSUE_CHARS] for i in (review.get("issues") or [])][:MAX_ISSUES]
        return {
            "sample_visible": bool(review["sample_visible"]),
            "matches_expected": bool(review["matches_expected"]),
            "issues": [_BANNED_RE.sub("", i).strip() for i in issues if i.strip()],
            "advice": _BANNED_RE.sub("", str(review.get("advice", "")))[:200].strip(),
        }
    except (KeyError, TypeError, AttributeError):
        return None
