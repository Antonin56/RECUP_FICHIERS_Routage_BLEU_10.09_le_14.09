"""iter108 — Backend regression tests for the armateur bug fixes.

P0 — Route determinism (departure_ts rounded to 600s)
P0 — Route without tide (non-regression, threshold_m=2.0)
P1 — Auth rate limit assoupli (20/5min instead of 5/5min)
P1 — Seamark tile proxy
P2 — 3 deleted terrestrial reports absent
"""
from __future__ import annotations

import os
import time
import uuid

import pytest
import requests

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")

# admin phone from test_credentials.md
ADMIN_PHONE = "0760071445"
OTP_CODE = "123456"

DELETED_IDS = [
    "40014394bacf4080ae5f511c83f4b764",
    "1ff784b3ed104c82953c674efafafd82",
    "eca354980ab0407ca2c0cb1c9e131e1e",
]


@pytest.fixture(scope="module")
def admin_token():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/otp/request", json={"phone": ADMIN_PHONE})
    assert r.status_code in (200, 429), f"otp/request status={r.status_code} body={r.text}"
    r = s.post(f"{BASE_URL}/api/auth/otp/verify",
               json={"phone": ADMIN_PHONE, "code": OTP_CODE})
    assert r.status_code == 200, f"otp/verify failed: {r.status_code} {r.text}"
    data = r.json()
    assert "token" in data
    return data["token"]


@pytest.fixture
def auth_client(admin_token):
    s = requests.Session()
    s.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {admin_token}",
    })
    return s


# ── P0 — Determinism (arrondi 600s) ────────────────────────────────────────
class TestRouteDeterminism:
    ROUTE_BODY = {
        "start": {"lat": 47.554, "lng": -2.876},
        "end": {"lat": 47.475, "lng": -3.105},
        "use_tide": True,
    }

    def test_route_deterministic_same_window(self, auth_client):
        """Two identical requests in the same 10-min window → identical waypoints."""
        r1 = auth_client.post(f"{BASE_URL}/api/routes/compute",
                              json=self.ROUTE_BODY, timeout=120)
        assert r1.status_code == 200, f"1st compute: {r1.status_code} {r1.text[:400]}"
        d1 = r1.json()

        r2 = auth_client.post(f"{BASE_URL}/api/routes/compute",
                              json=self.ROUTE_BODY, timeout=120)
        assert r2.status_code == 200, f"2nd compute: {r2.status_code} {r2.text[:400]}"
        d2 = r2.json()

        # tide info: 29/07 (routage 100 % ZH, marée désactivée) — plus
        # d'info marée dans la réponse ; on vérifie seulement l'absence
        # d'incohérence quand elle réapparaîtra (abonnement SHOM pro).
        t1, t2 = d1.get("tide"), d2.get("tide")
        if t1 is not None and t2 is not None:
            assert t1["departure_ts"] == t2["departure_ts"], (
                f"departure_ts differ: {t1['departure_ts']} vs {t2['departure_ts']}")
            assert int(t1["departure_ts"]) % 600 == 0, (
                f"departure_ts NOT multiple of 600: {t1['departure_ts']}")

        wp1 = [(round(p["lat"], 6), round(p["lng"], 6)) for p in d1["waypoints"]]
        wp2 = [(round(p["lat"], 6), round(p["lng"], 6)) for p in d2["waypoints"]]
        assert wp1 == wp2, (
            f"Waypoints DIFFER between two identical requests: "
            f"len1={len(wp1)} len2={len(wp2)} first_diff="
            f"{next(((i, wp1[i], wp2[i]) for i in range(min(len(wp1), len(wp2))) if wp1[i] != wp2[i]), None)}"
        )


# ── P0 — Route without tide (non-regression) ───────────────────────────────
class TestRouteNoTide:
    def test_route_no_tide(self, auth_client):
        body = {
            "start": {"lat": 47.554, "lng": -2.876},
            "end": {"lat": 47.475, "lng": -3.105},
            "use_tide": False,
        }
        r = auth_client.post(f"{BASE_URL}/api/routes/compute",
                             json=body, timeout=120)
        assert r.status_code == 200, f"no-tide compute: {r.status_code} {r.text[:400]}"
        d = r.json()
        assert "tide" not in d, f"tide should be absent when use_tide=False; got {d.get('tide')}"
        assert d.get("threshold_m") == 2.0, (
            f"threshold_m expected 2.0 got {d.get('threshold_m')}")
        assert len(d.get("waypoints", [])) >= 2


# ── P1 — Auth rate limit assoupli (20/5min) ────────────────────────────────
class TestAuthRateLimit:
    def test_login_rate_limit_relaxed(self):
        """8 consecutive login attempts must NOT return 429 (limit is now 20/5min)."""
        # Use a session WITHOUT the bypass header — hits real limiter.
        # Randomize X-Forwarded-For so this test's IP bucket is fresh.
        fake_ip = f"203.0.113.{uuid.uuid4().int % 250 + 1}"
        s = requests.Session()
        s.headers.update({
            "Content-Type": "application/json",
            "X-Forwarded-For": fake_ip,
            # Ensure we DON'T carry the bypass header from conftest.
            "X-RateLimit-Bypass": "",
        })
        got_429 = []
        for i in range(8):
            r = s.post(f"{BASE_URL}/api/auth/login",
                       json={"email": f"nobody+{i}@example.invalid",
                             "password": "wrong123"})
            if r.status_code == 429:
                got_429.append((i, r.status_code))
        assert not got_429, (
            f"Got 429 in first 8 attempts (limit should be 20/5min): {got_429}")


# ── P1 — Tile proxy seamark ────────────────────────────────────────────────
class TestSeamarkTiles:
    def test_seamark_tile_ok(self):
        # Public endpoint (no auth required in most tile proxies).
        url = f"{BASE_URL}/api/tiles/seamark/14/8060/5721.png"
        r1 = requests.get(url, timeout=30)
        assert r1.status_code == 200, f"1st tile: {r1.status_code} {r1.headers}"
        assert "image" in r1.headers.get("Content-Type", ""), (
            f"expected image, got {r1.headers.get('Content-Type')}")
        assert len(r1.content) > 100  # non-empty PNG
        t0 = time.monotonic()
        r2 = requests.get(url, timeout=30)
        dt = time.monotonic() - t0
        assert r2.status_code == 200
        # 2nd hit should hit cache — allow up to 5s (network variance).
        assert dt < 5.0, f"2nd tile took {dt:.2f}s (cache miss?)"


# ── P2 — Reports terrestres supprimés ──────────────────────────────────────
class TestDeletedReports:
    @pytest.mark.parametrize("rid", DELETED_IDS)
    def test_report_not_found(self, auth_client, rid):
        r = auth_client.get(f"{BASE_URL}/api/reports/{rid}")
        assert r.status_code == 404, (
            f"report id={rid} still exists (status={r.status_code}); should be deleted")
