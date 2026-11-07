"""Scan orchestration: validate, gate, measure, store. HTTP-agnostic."""

from __future__ import annotations

import contextlib
import logging
import re
import uuid

from ..agent.lab_agent import LabAgent
from ..data.store import Store
from ..domain import foods
from ..services.runs import Caller
from .features import extract_features
from .matching import MIN_GENUINE, compare, genuine_references
from .models import target_findings
from .quality import check_capture
from .schemas import Finding, Match, Quality, ScanRequest, ScanResult

log = logging.getLogger("sift.scan")

_NUMBER_RE = re.compile(r"(?<![\w.])-?\d+(?:[.,]\d+)?")


def _numbers(text: str) -> list[float]:
    """Every number in the template, so the agent may repeat them but never invent new ones."""
    out = []
    for m in _NUMBER_RE.findall(text):
        with contextlib.suppress(ValueError):
            out.append(float(m.replace(",", ".")))
    return out


def _template_report(profile: dict, device: str, match: Match, findings: list[Finding]) -> str:
    """Deterministic report. It never says safe, pure or fake; a differs result names the
    profile's likely causes instead of claiming adulteration."""
    name = profile["name"]
    if match.status == "matches":
        text = f"This scan matches the {match.n_genuine} genuine reference scans for {name} on {device}."
    elif match.status == "differs":
        causes = list(dict.fromkeys(c for t in profile["targets"] for c in t["likely_causes"]))
        text = (f"This scan differs from the {match.n_genuine} genuine reference scans for {name} on {device}. "
                f"This is not proof of adulteration. Possible causes include: {'; '.join(causes)}.")
    else:
        text = (f"No verdict yet: Sift holds {match.n_genuine} of {MIN_GENUINE} genuine reference scans for {name} "
                f"on {device}. A match result needs {MIN_GENUINE}.")
    # Findings are returned as structured data; the text stays a readable paragraph.
    return text


class ScanService:
    def __init__(self, store: Store, agent: LabAgent):
        self.store, self.agent = store, agent

    def run(self, request: ScanRequest, caller: Caller) -> ScanResult:
        profile = foods.get(request.food)
        device = (request.device or "").strip() or "unknown"
        owner = caller.owner
        quality, usable = check_capture(request.capture, profile)
        features = extract_features(request.capture, usable)
        scan_id = uuid.uuid4().hex[:12]
        barcode = request.product.barcode if request.product else None
        ref = request.reference
        if not usable:
            return self._finish_rejected(scan_id, profile, device, owner, request.mode, barcode, ref, quality)
        if request.mode == "reference":
            return self._finish_reference(scan_id, profile, device, owner, barcode, ref, quality, features)
        return self._finish_check(scan_id, profile, device, owner, barcode, quality, features)

    def _store(self, scan_id: str, food: str, device: str, owner: str, mode: str, barcode: str | None,
               ref, features: dict, result: ScanResult) -> None:
        self.store.save_scan(scan_id, food, device, owner, mode, ref.label if ref else None,
                             ref.target if ref else None, ref.value if ref else None, barcode, features,
                             result.model_dump())
        log.info("scan", extra={"fields": {"scan": scan_id, "food": food, "mode": mode, "status": result.status,
                                           "match": result.match.status}})

    def _finish_rejected(self, scan_id: str, profile: dict, device: str, owner: str, mode: str,
                         barcode: str | None, ref, quality: Quality) -> ScanResult:
        fixes = " ".join(p.fix for p in quality.problems if p.severity == "reject")
        result = ScanResult(scan_id=scan_id, food=profile["id"], mode=mode, status="rejected", quality=quality,
                            match=Match(status="no_reference",
                                        n_genuine=len(genuine_references(self.store, profile["id"], device, owner))),
                            findings=[], report={"agent": "offline", "text": f"This scan couldn't be read. {fixes}"})
        self._store(scan_id, profile["id"], device, owner, mode, barcode, ref, {}, result)
        return result

    def _finish_reference(self, scan_id: str, profile: dict, device: str, owner: str, barcode: str | None,
                          ref, quality: Quality, features: dict) -> ScanResult:
        findings = target_findings(profile, features, device, self.store, owner)
        n_genuine = len(genuine_references(self.store, profile["id"], device, owner)) + (ref.label == "genuine")
        text = (f"Stored as a {ref.label} reference scan for {profile['name']} on {device}. The library now holds "
                f"{n_genuine} genuine reference scans for this phone.")
        result = ScanResult(scan_id=scan_id, food=profile["id"], mode="reference", status="stored", quality=quality,
                            match=Match(status="no_reference", n_genuine=n_genuine, modalities=sorted(features)),
                            findings=findings, report={"agent": "offline", "text": text})
        self._store(scan_id, profile["id"], device, owner, "reference", barcode, ref, features, result)
        return result

    def _finish_check(self, scan_id: str, profile: dict, device: str, owner: str, barcode: str | None,
                      quality: Quality, features: dict) -> ScanResult:
        match = compare(features, genuine_references(self.store, profile["id"], device, owner))
        findings = target_findings(profile, features, device, self.store, owner)
        template = _template_report(profile, device, match, findings)
        allowed = {f"n{i}": v for i, v in enumerate(_numbers(template))}
        if match.distance is not None:
            allowed["distance"] = match.distance
        if match.threshold is not None:
            allowed["threshold"] = match.threshold
        facts = {"food": profile["id"], "match": match.model_dump(), "verdict": {"matches": "pass",
                 "differs": "flag"}.get(match.status), "quality": allowed}
        report = self.agent.write_scan_report(profile, facts, template)
        result = ScanResult(scan_id=scan_id, food=profile["id"], mode="check", status="ok", quality=quality,
                            match=match, findings=findings, report=report)
        self._store(scan_id, profile["id"], device, owner, "check", barcode, None, features, result)
        return result
