"""Iter99 (22/07/2026) — Marée intégrée au routage automatique.

POST /api/routes/compute + use_tide:true / departure_ts.
"""
import os
import time

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
PHONE = "0766071445"  # Aslak — dev_bypass


@pytest.fixture(scope="module")
def token():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/otp/request", json={"phone": PHONE})
    assert r.status_code in (200, 429), r.text
    if r.status_code == 429:
        # cooldown 30s → wait a bit
        time.sleep(31)
        r = s.post(f"{BASE_URL}/api/auth/otp/request", json={"phone": PHONE})
        assert r.status_code == 200, r.text
    r = s.post(f"{BASE_URL}/api/auth/otp/verify", json={"phone": PHONE, "code": "123456"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture
def api(token):
    s = requests.Session()
    s.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    })
    return s


BODY_BASE = {
    "start": {"lat": 47.610, "lng": -2.825},
    "end": {"lat": 47.348, "lng": -3.148},
    "draft_m": 1.5,
    "depth_margin_m": 0.5,
    "lateral_margin_m": 10,
}


class TestRouteTide:
    """P0 — Marée intégrée dans /api/routes/compute."""

    def test_p0_use_tide_now(self, api):
        body = {**BODY_BASE, "use_tide": True}
        r = api.post(f"{BASE_URL}/api/routes/compute", json=body, timeout=90)
        assert r.status_code == 200, r.text
        data = r.json()
        # If Open-Meteo down → warning "Marée indisponible" and no tide field.
        if "tide" not in data:
            warnings = data.get("warnings", [])
            assert any("indisponible" in w.lower() or "marée" in w.lower() for w in warnings), warnings
            pytest.skip("Open-Meteo down — tide fallback path (documented)")
        tide = data["tide"]
        assert "port" in tide and isinstance(tide["port"], str) and tide["port"], tide
        assert "height_start_m" in tide and "height_min_m" in tide
        assert "window_h" in tide and "departure_ts" in tide
        # tide_m derived (>= 0 clipped in server ; can technically be negative if below ZH → we accept -2..)
        assert "tide_m" in data
        assert data["tide_m"] >= -2.0
        # threshold = round(2.0 - tide_m, ±0.01)
        expected_thr = round(2.0 - data["tide_m"], 2)
        assert abs(data["threshold_m"] - expected_thr) <= 0.01, (
            f"threshold_m={data['threshold_m']} expected≈{expected_thr}"
        )
        # distance ~ 38-39 km
        assert 30000 <= data["distance_m"] <= 45000, data["distance_m"]

    def test_p0_use_tide_plus_4h(self, api):
        dep = time.time() + 4 * 3600
        body = {**BODY_BASE, "use_tide": True, "departure_ts": dep}
        r = api.post(f"{BASE_URL}/api/routes/compute", json=body, timeout=90)
        assert r.status_code == 200, r.text
        data = r.json()
        if "tide" not in data:
            pytest.skip("Open-Meteo down")
        # If min_depth_m < 2.0 → warning "UNIQUEMENT grâce à la marée"
        if data["min_depth_m"] < 2.0:
            warns = " ".join(data.get("warnings", []))
            assert "UNIQUEMENT" in warns and "marée" in warns.lower(), (
                f"warning manquant, warnings={data.get('warnings')}"
            )

    def test_p1_no_tide_default(self, api):
        r = api.post(f"{BASE_URL}/api/routes/compute", json=BODY_BASE, timeout=90)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "tide" not in data, "tide field should be absent when use_tide=false"
        assert data["threshold_m"] == 2.0, data["threshold_m"]

    def test_p1_use_tide_false(self, api):
        body = {**BODY_BASE, "use_tide": False}
        r = api.post(f"{BASE_URL}/api/routes/compute", json=body, timeout=90)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "tide" not in data
        assert data["threshold_m"] == 2.0

    def test_p1_departure_ts_negative_422(self, api):
        body = {**BODY_BASE, "use_tide": True, "departure_ts": -1}
        r = api.post(f"{BASE_URL}/api/routes/compute", json=body)
        assert r.status_code == 422, r.text
