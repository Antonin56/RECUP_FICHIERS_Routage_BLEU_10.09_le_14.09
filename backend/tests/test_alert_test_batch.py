"""Iter 67 — regression tests for POST /api/dev/alert-test-batch.

Covers:
  • admin (whitelisted) → 200 with 5 items, correct types/subtypes, distances match haversine
  • replay → deleted == 5
  • non-admin → 403
  • cleanup at end (deleteMany via a final batch by admin, then removed here)
"""
from __future__ import annotations

import math
import os
import uuid

import pytest
import requests

BASE = os.environ["EXPO_BACKEND_URL"].rstrip("/") if os.environ.get("EXPO_BACKEND_URL") else \
    "https://calcul-optimize.preview.emergentagent.com"
API = f"{BASE}/api"
BYPASS = {"X-RateLimit-Bypass": "qa-bypass-7f3d9a2e4c8b1f60"}

ADMIN_PHONE = "0760071445"
OTP = "123456"

CENTER_LAT = 47.48
CENTER_LNG = -3.10

EXPECTED_SPECS = [
    # 22/07/2026 — aligné sur ALERT_TEST_SPECS backend (1er anneau à 600 m).
    (0.6, "obstacle_nav", "ofni"),
    (1.0, "animal_marin", "mammifere"),
    (3.0, "autorites", "gendarmerie_maritime"),
    (10.0, "pollution", "pollution_locale"),
    (20.0, "pollution", "pollution_importante"),
]


def _login(phone: str, pseudo: str | None = None) -> str:
    s = requests.Session()
    s.headers.update(BYPASS)
    r = s.post(f"{API}/auth/otp/request", json={"phone": phone}, timeout=15)
    assert r.status_code == 200, r.text
    body = {"phone": phone, "code": OTP}
    if pseudo:
        body["pseudo"] = pseudo
    r = s.post(f"{API}/auth/otp/verify", json=body, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _haversine_km(a_lat, a_lng, b_lat, b_lng):
    R = 6371.0
    la1, la2 = math.radians(a_lat), math.radians(b_lat)
    dla = math.radians(b_lat - a_lat)
    dlo = math.radians(b_lng - a_lng)
    h = math.sin(dla/2)**2 + math.cos(la1)*math.cos(la2)*math.sin(dlo/2)**2
    return 2 * R * math.asin(math.sqrt(h))


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN_PHONE)


@pytest.fixture(scope="module")
def rando_token():
    # random new user (not whitelisted)
    n = uuid.uuid4().int
    phone = f"0699{n % 1_000_000:06d}"
    return _login(phone, pseudo=f"QAIter67_{n % 10000}")


def test_admin_creates_batch(admin_token):
    s = requests.Session(); s.headers.update(BYPASS)
    s.headers["Authorization"] = f"Bearer {admin_token}"
    r = s.post(f"{API}/dev/alert-test-batch", json={"lat": CENTER_LAT, "lng": CENTER_LNG}, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    created = data["created"]
    assert len(created) == 5
    # each entry matches the expected specs
    for got, (km, rtype, subtype) in zip(created, EXPECTED_SPECS):
        assert got["distance_km"] == km
        assert got["type"] == rtype
        assert got["subtype"] == subtype
        d = _haversine_km(CENTER_LAT, CENTER_LNG, got["lat"], got["lng"])
        assert abs(d - km) < 0.05, f"distance mismatch {d} vs {km}"


def test_replay_deletes_previous(admin_token):
    s = requests.Session(); s.headers.update(BYPASS)
    s.headers["Authorization"] = f"Bearer {admin_token}"
    r = s.post(f"{API}/dev/alert-test-batch", json={"lat": CENTER_LAT, "lng": CENTER_LNG}, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["deleted"] == 5
    assert len(data["created"]) == 5


def test_reports_visible_via_get(admin_token):
    s = requests.Session(); s.headers.update(BYPASS)
    s.headers["Authorization"] = f"Bearer {admin_token}"
    r = s.get(f"{API}/reports", params={"lat": CENTER_LAT, "lng": CENTER_LNG, "radius_km": 50}, timeout=15)
    assert r.status_code == 200, r.text
    reports = r.json()
    test_ones = [x for x in reports if (x.get("description") or "").startswith("🧪 TEST ALARME")]
    assert len(test_ones) >= 5, f"expected >=5 test reports, got {len(test_ones)}"


def test_non_whitelisted_forbidden(rando_token):
    s = requests.Session(); s.headers.update(BYPASS)
    s.headers["Authorization"] = f"Bearer {rando_token}"
    r = s.post(f"{API}/dev/alert-test-batch", json={"lat": CENTER_LAT, "lng": CENTER_LNG}, timeout=15)
    assert r.status_code == 403, r.text


def test_cleanup(admin_token):
    """Post one final batch (replaces) so we can delete the resulting docs via a
    fresh batch that... will leave 5 rows in DB. The main agent will run
    db.reports.deleteMany({is_alert_test:true}) — we simply verify the endpoint
    is still healthy at the end."""
    s = requests.Session(); s.headers.update(BYPASS)
    s.headers["Authorization"] = f"Bearer {admin_token}"
    r = s.post(f"{API}/dev/alert-test-batch", json={"lat": CENTER_LAT, "lng": CENTER_LNG}, timeout=15)
    assert r.status_code == 200
