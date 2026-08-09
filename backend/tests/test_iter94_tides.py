"""Iter94 — Tests marées /api/tides/nearest (Open-Meteo approché)."""
import os

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")


@pytest.fixture
def api_client():
    s = requests.Session()
    s.headers.update({"X-RateLimit-Bypass": "qa-bypass-7f3d9a2e4c8b1f60"})
    return s


class TestTides:
    """GET /api/tides/nearest"""

    def test_nearest_port_navalo(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/tides/nearest", params={"lat": 47.55, "lng": -2.91})
        assert r.status_code == 200, r.text
        data = r.json()
        # port structure
        assert "port" in data and data["port"]["name"] == "Port-Navalo", data["port"]
        assert "nearest_ports" in data and len(data["nearest_ports"]) == 3
        # days
        assert "days" in data and len(data["days"]) == 5, f"expected 5 days, got {len(data['days'])}"
        for day in data["days"]:
            assert "date" in day and "events" in day
            for e in day["events"]:
                assert e["type"] in ("BM", "PM")
                assert isinstance(e["time"], str) and ":" in e["time"]
                assert isinstance(e["height_m"], (int, float))
        # au moins une PM avec coef non-null
        pm_with_coef = [
            e for d in data["days"] for e in d["events"]
            if e["type"] == "PM" and e.get("coef") is not None
        ]
        assert len(pm_with_coef) > 0, "aucune PM avec coefficient non-null"

    def test_invalid_lat(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/tides/nearest", params={"lat": 999, "lng": -2.91})
        assert r.status_code == 422, r.text

    def test_invalid_lng(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/tides/nearest", params={"lat": 47.55, "lng": 999})
        assert r.status_code == 422, r.text

    def test_missing_params(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/tides/nearest")
        assert r.status_code == 422, r.text
