"""Iter120 — P0 backend tests: GET /api/tides/curve + non-regression POST /api/routes/compute."""
import os
import sys

import pytest
import requests

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
from core.auth import make_jwt  # noqa: E402


BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")


@pytest.fixture(scope="module")
def token():
    return make_jwt("user_0b6070a69154")


@pytest.fixture(scope="module")
def auth_client(token):
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    return s


# ── /api/tides/curve ────────────────────────────────────────────────────────
class TestTidesCurve:
    def test_curve_valid(self):
        r = requests.get(f"{BASE_URL}/api/tides/curve", params={"lat": 47.61, "lng": -2.83}, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "port" in data and isinstance(data["port"], str) and data["port"]
        assert "points" in data and isinstance(data["points"], list)
        # 24h at 30 min step → ~49 points; contract says ≥ 40
        assert len(data["points"]) >= 40, f"only {len(data['points'])} points (expected ≥ 40)"
        for p in data["points"][:3]:
            assert "ts" in p and "h" in p
            assert isinstance(p["ts"], int)
            assert isinstance(p["h"], (int, float))

    def test_curve_lat_out_of_range(self):
        r = requests.get(f"{BASE_URL}/api/tides/curve", params={"lat": 999, "lng": -2.83}, timeout=15)
        assert r.status_code == 422, f"expected 422 got {r.status_code}"

    def test_curve_lng_out_of_range(self):
        r = requests.get(f"{BASE_URL}/api/tides/curve", params={"lat": 47.61, "lng": 999}, timeout=15)
        assert r.status_code == 422, f"expected 422 got {r.status_code}"

    def test_curve_missing_param(self):
        r = requests.get(f"{BASE_URL}/api/tides/curve", params={"lat": 47.61}, timeout=15)
        assert r.status_code == 422


# ── /api/routes/compute (non-regression iter119) ────────────────────────────
class TestRoutesComputeRegression:
    def test_deep_water_golfe_tide_zero_and_marée_basse_warning(self, auth_client):
        payload = {
            "start": {"lat": 47.610, "lng": -2.825},
            "end": {"lat": 47.595, "lng": -2.851},
            "draft_m": 1.5,
            "depth_margin_m": 0.5,
            "use_tide": True,
        }
        r = auth_client.post(f"{BASE_URL}/api/routes/compute", json=payload, timeout=60)
        assert r.status_code == 200, r.text
        data = r.json()
        # Iter119 behaviour: tide_m == 0.0 (route computed at ZH), warnings contain 'MARÉE BASSE'
        assert data.get("tide_m") == 0.0, f"expected tide_m=0.0, got {data.get('tide_m')}"
        warnings = data.get("warnings") or []
        joined = " || ".join(warnings)
        assert "MARÉE BASSE" in joined, f"missing 'MARÉE BASSE' warning, got: {warnings}"
