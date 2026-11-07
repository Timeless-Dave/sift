"""Food profiles for instant scans: one YAML file per food in domain/foods/ (docs/scanner.md).

A profile says which phone sensors a scan uses, how to hold the phone (one line, not a protocol),
and which questions (targets) Sift is working on for that food, each with an honest status and
its sources. Bad files fail at startup with the file name and what to fix.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from ..core.errors import NotFound

FOOD_DIR = Path(__file__).parent / "foods"
SENSING = ("torch", "screenlight", "acoustic", "vibration", "contact", "bubble")
KINDS = ("adulteration", "cultured", "freshness", "identity")
STATUSES = ("research", "experimental", "validated")
CATEGORIES = ("oil", "dairy", "meat", "fish", "spice", "honey", "other")


class FoodNotFound(NotFound):
    pass


@lru_cache(maxsize=1)
def load_all() -> dict[str, dict[str, Any]]:
    foods: dict[str, dict[str, Any]] = {}
    for path in sorted(FOOD_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text())
        except yaml.YAMLError as exc:
            raise ValueError(f"{path.name}: invalid YAML: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"{path.name}: a food profile must be a mapping")
        _validate(data, path.name)
        if data["id"] in foods:
            raise ValueError(f"{path.name}: duplicate food id {data['id']!r}")
        foods[data["id"]] = data
    return foods


def get(food_id: str) -> dict[str, Any]:
    try:
        return load_all()[food_id]
    except KeyError as exc:
        raise FoodNotFound(f"Sift has no profile for '{food_id}'.") from exc


def _need(cond: bool, where: str, msg: str) -> None:
    if not cond:
        raise ValueError(f"{where}: {msg}")


def _ref_list(refs: Any, where: str) -> None:
    _need(isinstance(refs, list) and refs, where, "needs at least one reference")
    for r in refs:
        _need(isinstance(r, dict) and all(isinstance(r.get(k), str) and r[k].strip() for k in
                                          ("title", "source", "url", "finding")),
              where, "each reference needs title, source, url and finding")
        _need(r["url"].startswith("https://"), where, f"reference url must be https: {r['url']}")


def _validate(f: dict[str, Any], name: str) -> None:
    for key in ("id", "name", "category", "aliases", "scan", "targets", "references"):
        _need(key in f, name, f"missing '{key}'")
    where = f"{name} ({f['id']})"
    _need(isinstance(f["id"], str) and f["id"] == name.removesuffix(".yaml"), where, "id must match the file name")
    _need(f["category"] in CATEGORIES, where, f"category must be one of {CATEGORIES}")
    _need(isinstance(f["aliases"], list) and all(isinstance(a, str) for a in f["aliases"]), where,
          "aliases must be a list of names people call this food")
    scan = f["scan"]
    _need(isinstance(scan, dict), where, "scan must be a mapping")
    mods = scan.get("modalities")
    _need(isinstance(mods, list) and mods and all(m in SENSING for m in mods), where,
          f"scan.modalities must be a non-empty subset of {SENSING}")
    _need(isinstance(scan.get("placement"), str) and 0 < len(scan["placement"]) <= 120, where,
          "scan.placement must be one short sentence (at most 120 characters) on how to hold the phone")
    if "off_category_tags" in f:
        _need(isinstance(f["off_category_tags"], list), where, "off_category_tags must be a list")
    targets = f["targets"]
    _need(isinstance(targets, list) and targets, where, "needs at least one target")
    seen = set()
    for t in targets:
        tw = f"{where} target {t.get('id', '?') if isinstance(t, dict) else '?'}"
        _need(isinstance(t, dict), tw, "target must be a mapping")
        for key in ("id", "kind", "question", "status", "signals", "likely_causes", "references"):
            _need(key in t, tw, f"missing '{key}'")
        _need(t["id"] not in seen, tw, "duplicate target id")
        seen.add(t["id"])
        _need(t["kind"] in KINDS, tw, f"kind must be one of {KINDS}")
        _need(t["status"] in STATUSES, tw, f"status must be one of {STATUSES}")
        _need(t["status"] != "validated", tw,
              "only Sift's own validation runs can mark a target validated; use experimental or research")
        if t["kind"] == "cultured":
            _need(t["status"] == "research", tw, "cultured-vs-conventional targets stay 'research' until validated")
        _need(isinstance(t["signals"], dict) and t["signals"] and all(m in mods for m in t["signals"]), tw,
              "signals maps each modality the target relies on (from scan.modalities) to why it carries signal")
        _need(isinstance(t["likely_causes"], list) and t["likely_causes"], tw,
              "likely_causes lists what a 'differs from genuine' result could mean, so the wording stays honest")
        _ref_list(t["references"], tw)
    _ref_list(f["references"], where)
