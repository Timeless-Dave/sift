"""Food profiles load, validate and keep their honesty promises (docs/scanner.md)."""

import pytest

from sift.domain import foods

EXPECTED = {"olive-oil", "cow-milk", "beef", "chicken", "fish-fillet", "turmeric", "chilli-powder", "honey", "sunflower-oil"}


def test_all_profiles_load_and_cover_the_asked_foods():
    all_foods = foods.load_all()
    assert set(all_foods) >= EXPECTED, f"missing profiles: {EXPECTED - set(all_foods)}"
    for food_id, food in all_foods.items():
        assert food["id"] == food_id
        assert food["targets"], f"{food_id} needs at least one target"


def test_ids_unique_and_aliases_non_empty():
    seen = set()
    for food in foods.load_all().values():
        assert food["id"] not in seen
        seen.add(food["id"])
        assert food["aliases"] and all(a.strip() for a in food["aliases"]), f"{food['id']} needs aliases"
        target_ids = [t["id"] for t in food["targets"]]
        assert len(set(target_ids)) == len(target_ids), f"{food['id']} has duplicate target ids"


def test_every_cultured_target_is_research():
    cultured = [(f["id"], t["id"], t["status"]) for f in foods.load_all().values() for t in f["targets"]
                if t["kind"] == "cultured"]
    assert {f for f, _, _ in cultured} == {"beef", "chicken"}
    assert all(s == "research" for _, _, s in cultured), cultured


def test_every_profile_uses_only_sensing_modalities():
    for food in foods.load_all().values():
        mods = food["scan"]["modalities"]
        assert mods and set(mods) <= set(foods.SENSING), f"{food['id']}: {mods}"
        assert len(food["scan"]["placement"]) <= 120, f"{food['id']} placement too long"
        for t in food["targets"]:
            assert t["signals"] and set(t["signals"]) <= set(mods), f"{food['id']}/{t['id']}"


def test_no_target_claims_validated():
    for food in foods.load_all().values():
        for t in food["targets"]:
            assert t["status"] in ("research", "experimental"), f"{food['id']}/{t['id']}"


def test_references_are_https_with_findings():
    def check(refs, where):
        assert refs, f"{where} needs at least one reference"
        for r in refs:
            assert r["url"].startswith("https://"), f"{where}: {r['url']}"
            assert r["title"].strip() and r["source"].strip() and r["finding"].strip(), where

    for food in foods.load_all().values():
        check(food["references"], food["id"])
        for t in food["targets"]:
            check(t["references"], f"{food['id']}/{t['id']}")


def test_unknown_food_raises_not_found():
    with pytest.raises(foods.FoodNotFound):
        foods.get("unicorn-milk")
