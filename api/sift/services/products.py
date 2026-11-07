"""Barcode lookup over Open Food Facts: product name plus which food profile it maps to.

The mapping comes from each profile's `off_category_tags`; when several tags match,
the most specific one (last in the product's categories_tags) wins. Found products
are cached in-process for 24 hours; misses and outages are never cached.
"""

from __future__ import annotations

import logging
import re
import threading
import time

import httpx

from ..core.config import Settings
from ..core.errors import InvalidInput, NotFound, Unavailable
from ..domain import foods

log = logging.getLogger("sift.products")

USER_AGENT = "SiftLab/0.2 (+https://github.com/Timeless-Dave/sift)"
FIELDS = "product_name,brands,categories_tags"
TIMEOUT = 5.0
CACHE_TTL = 24 * 3600
CACHE_MAX = 1000
MAX_TEXT = 200
BARCODE_RE = re.compile(r"^[0-9]{6,14}$")
UNAVAILABLE = "Product lookup is unavailable; pick the food instead."


def map_food(categories_tags: list) -> str | None:
    """Map OFF category tags to a food profile id. Most specific (last) match wins."""
    tags = [str(t).strip().lower() for t in categories_tags if isinstance(t, str) and t.strip()]
    profiles = foods.load_all()
    wanted = {fid: {str(t).strip().lower() for t in (prof.get("off_category_tags") or []) if isinstance(t, str)}
              for fid, prof in profiles.items()}
    for tag in reversed(tags):
        for fid in sorted(wanted):
            if tag in wanted[fid]:
                return fid
    return None


class ProductService:
    """OFF product lookup with a bounded in-process TTL cache. `transport` is for tests."""

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self._http = httpx.Client(base_url=settings.off_base_url.rstrip("/") or "https://world.openfoodfacts.org",
                                  headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, transport=transport)
        self._cache: dict[str, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    def lookup(self, barcode: str) -> dict:
        if not isinstance(barcode, str) or not BARCODE_RE.match(barcode):
            raise InvalidInput("Barcodes are 6 to 14 digits. Check the number and try again.")
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(barcode)
            if hit and hit[0] > now:
                return dict(hit[1])
            if hit:
                del self._cache[barcode]
        try:
            r = self._http.get(f"/api/v2/product/{barcode}.json", params={"fields": FIELDS})
        except httpx.HTTPError as exc:
            log.warning("OFF lookup failed: %s", type(exc).__name__)
            raise Unavailable(UNAVAILABLE) from exc
        if r.status_code == 404:
            raise NotFound(f"No product found for barcode {barcode}. Pick the food instead.")
        if r.status_code != 200:
            log.warning("OFF lookup failed: HTTP %s", r.status_code)
            raise Unavailable(UNAVAILABLE)
        try:
            data = r.json()
        except ValueError as exc:
            log.warning("OFF lookup failed: response was not JSON")
            raise Unavailable(UNAVAILABLE) from exc
        product = data.get("product") if isinstance(data, dict) else None
        if not isinstance(data, dict) or data.get("status") == 0 or not isinstance(product, dict):
            raise NotFound(f"No product found for barcode {barcode}. Pick the food instead.")
        tags = product.get("categories_tags") or []
        result = {"barcode": barcode,
                  "name": str(product.get("product_name") or "")[:MAX_TEXT],
                  "brands": str(product.get("brands") or "")[:MAX_TEXT],
                  "food": map_food(tags if isinstance(tags, list) else []),
                  "source": "openfoodfacts"}
        with self._lock:
            while len(self._cache) >= CACHE_MAX:
                self._cache.pop(next(iter(self._cache)))
            self._cache[barcode] = (now + CACHE_TTL, result)
        return dict(result)
