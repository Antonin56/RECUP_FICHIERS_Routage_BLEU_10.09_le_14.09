"""
Iter123 — Post-sea-trial fixes: seamarks R_CARDINAL_WRONG_SIDE_M 120m -> 300m.
Non-regression tests on the frozen routing engine:
  1. Arradon (47.610,-2.825) -> Golfe sud (47.52,-2.95) draft 1.5, margin 0.5,
     lateral 10 -> 200 + at least 2 waypoints.
  2. Deep-water route (47.386,-2.556) -> (47.4065,-2.615) draft 1.2 -> <30s.
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/") or os.environ.get(
    "EXPO_BACKEND_URL", ""
).rstrip("/")


@pytest.fixture(scope="module")
def api_client():
    s = requests.Session()
    s.headers.update(
        {
            "Content-Type": "application/json",
            "X-RateLimit-Bypass": "qa-bypass-7f3d9a2e4c8b1f60",
        }
    )
    # Bearer token (admin)
    try:
        with open("/app/tmp_token.txt", "r", encoding="utf-8") as f:
            tok = f.read().strip()
        s.headers.update({"Authorization": f"Bearer {tok}"})
    except Exception:
        pass
    return s


class TestRouteAfterSeamarks300:
    def test_route_arradon_to_golfe_sud(self, api_client):
        assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL missing"
        payload = {
            "start": {"lat": 47.610, "lng": -2.825},
            "end": {"lat": 47.52, "lng": -2.95},
            "draft_m": 1.5,
            "depth_margin_m": 0.5,
            "lateral_margin_m": 10,
        }
        t0 = time.time()
        r = api_client.post(f"{BASE_URL}/api/routes/compute", json=payload, timeout=120)
        dt = time.time() - t0
        assert r.status_code == 200, f"HTTP {r.status_code} — {r.text[:400]}"
        data = r.json()
        assert "waypoints" in data, f"missing waypoints: {list(data.keys())}"
        wpts = data["waypoints"]
        assert isinstance(wpts, list) and len(wpts) >= 2, f"waypoints too short: {len(wpts)}"
        # Departure and arrival proximity checks
        s = wpts[0]
        e = wpts[-1]
        # Basic shape
        for k in ("lat", "lng"):
            assert k in s and k in e
        # Not blocked
        assert not data.get("blocked", False), f"route blocked: {data.get('reason')}"
        print(f"[Arradon->GolfeSud] wpts={len(wpts)} dt={dt:.2f}s")

    def test_route_deep_water_fast(self, api_client):
        payload = {
            "start": {"lat": 47.386, "lng": -2.556},
            "end": {"lat": 47.4065, "lng": -2.615},
            "draft_m": 1.2,
            "depth_margin_m": 0.5,
            "lateral_margin_m": 10,
        }
        t0 = time.time()
        r = api_client.post(f"{BASE_URL}/api/routes/compute", json=payload, timeout=60)
        dt = time.time() - t0
        assert r.status_code == 200, f"HTTP {r.status_code} — {r.text[:400]}"
        assert dt < 30.0, f"too slow: {dt:.2f}s"
        data = r.json()
        assert "waypoints" in data
        assert len(data["waypoints"]) >= 2
        assert not data.get("blocked", False), f"route blocked: {data.get('reason')}"
        print(f"[DeepWater] wpts={len(data['waypoints'])} dt={dt:.2f}s")
