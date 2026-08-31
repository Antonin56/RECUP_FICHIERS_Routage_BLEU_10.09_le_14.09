"""
Iteration 66 — Map regression backend smoke.

Just verifies the anonymous demo /api/reports endpoint still returns ~30 demo
reports (no backend changes this iteration; UI-only regression fix).
"""
import os
import requests

BASE_URL = os.environ.get("EXPO_BACKEND_URL", "https://nav-engine-i.preview.emergentagent.com").rstrip("/")


def test_get_reports_anonymous_demo_returns_seed():
    r = requests.get(f"{BASE_URL}/api/reports", timeout=15)
    assert r.status_code == 200, f"Expected 200 got {r.status_code}: {r.text[:200]}"
    data = r.json()
    items = data if isinstance(data, list) else data.get("items") or data.get("reports") or []
    assert isinstance(items, list)
    assert len(items) >= 20, f"Expected ~30 demo reports, got {len(items)}"
    # Structural sanity
    sample = items[0]
    for k in ("id", "type", "lat", "lng"):
        assert k in sample, f"missing key {k} in report"
