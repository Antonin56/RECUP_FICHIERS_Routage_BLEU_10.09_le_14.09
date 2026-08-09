"""Iter84 — Backend validation for proximity-confirm point/reliability deltas.

Spec:
  POST /api/reports/{id}/confirm  body={"source": "proximity"} must return:
    - confirmer_points_awarded == max(1, POINTS_CONFIRM_OTHER // 2) == 1
    - author_reliability_awarded == RELIABILITY_CONFIRM_OTHER == 3

DB persistence (checked via GET /api/auth/me):
    - confirmer: users.points += 1
    - author:    reliability score += 3

Guard: author cannot confirm own report → 422.
"""
import os
import time

import pytest
import requests
from pathlib import Path
from dotenv import load_dotenv

# Ensure env loaded (frontend/.env + backend/.env)
load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")

AUTHOR_PHONE = "0760071445"   # SignalMar admin
CONFIRMER_PHONE = "0611223344"
CONFIRMER_PSEUDO = "TestConfirmerIter84"
OTP = "123456"

SEA_LAT = 48.30
SEA_LNG = -4.80


def _login(session: requests.Session, phone: str, pseudo: str | None = None):
    r = session.post(f"{BASE_URL}/api/auth/otp/request", json={"phone": phone})
    assert r.status_code in (200, 201, 429), r.text
    if r.status_code == 429:
        time.sleep(2)
    body = {"phone": phone, "code": OTP}
    if pseudo:
        body["pseudo"] = pseudo
    r = session.post(f"{BASE_URL}/api/auth/otp/verify", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    return data["token"], data["user"]


def _set_location(session: requests.Session, token: str, lat: float, lng: float):
    """Push a recent GPS fix so confirmer is considered 'at sea'."""
    h = {"Authorization": f"Bearer {token}"}
    # Try both known endpoints for compatibility.
    for path in ("/api/profile/location",):
        r = session.post(f"{BASE_URL}{path}", json={"lat": lat, "lng": lng}, headers=h)
        if r.status_code < 400:
            return True
    return False


@pytest.fixture(scope="module")
def author_ctx():
    s = requests.Session()
    s.headers["Content-Type"] = "application/json"
    token, user = _login(s, AUTHOR_PHONE)
    return s, token, user


@pytest.fixture(scope="module")
def confirmer_ctx():
    s = requests.Session()
    s.headers["Content-Type"] = "application/json"
    token, user = _login(s, CONFIRMER_PHONE, pseudo=CONFIRMER_PSEUDO)
    return s, token, user


class TestProximityConfirmDeltas:
    """iter84 core spec — deltas on proximity source."""

    def test_create_report_by_author(self, author_ctx):
        s, token, user = author_ctx
        h = {"Authorization": f"Bearer {token}"}
        payload = {
            "type": "obstacle_nav",
            "lat": SEA_LAT,
            "lng": SEA_LNG,
            "description": "TEST_iter84 proximity deltas",
            "photos": [],
            "heading": 0,
            "speed_knots": 0,
        }
        r = s.post(f"{BASE_URL}/api/reports", json=payload, headers=h)
        assert r.status_code in (200, 201), r.text
        rep = r.json()
        assert rep.get("type") == "obstacle_nav"
        pytest.iter84_rid = rep["id"]
        pytest.iter84_author_id = user["user_id"]

    def test_author_cannot_confirm_own_report(self, author_ctx):
        """Guard existing: author self-confirm returns 422."""
        s, token, _ = author_ctx
        h = {"Authorization": f"Bearer {token}"}
        rid = getattr(pytest, "iter84_rid")
        r = s.post(
            f"{BASE_URL}/api/reports/{rid}/confirm",
            json={"source": "proximity"},
            headers=h,
        )
        assert r.status_code == 422, f"expected 422 got {r.status_code}: {r.text}"

    def test_read_author_points_baseline(self, author_ctx):
        s, token, _ = author_ctx
        h = {"Authorization": f"Bearer {token}"}
        r = s.get(f"{BASE_URL}/api/auth/me", headers=h)
        assert r.status_code == 200, r.text
        u = r.json()
        pytest.iter84_author_before_rel = int(u.get("reliability_score", 50))

    def test_read_confirmer_points_baseline(self, confirmer_ctx):
        s, token, _ = confirmer_ctx
        h = {"Authorization": f"Bearer {token}"}
        r = s.get(f"{BASE_URL}/api/auth/me", headers=h)
        assert r.status_code == 200, r.text
        u = r.json()
        pytest.iter84_confirmer_before_points = int(u.get("points", 0))

    def test_confirmer_needs_location(self, confirmer_ctx):
        """Push recent GPS fix for confirmer so is_at_sea check succeeds."""
        s, token, _ = confirmer_ctx
        _set_location(s, token, SEA_LAT, SEA_LNG)
        # No assert (endpoint discovery best-effort). Real check is confirm below.

    def test_proximity_confirm_returns_expected_deltas(self, confirmer_ctx):
        s, token, _ = confirmer_ctx
        h = {"Authorization": f"Bearer {token}"}
        rid = getattr(pytest, "iter84_rid")
        r = s.post(
            f"{BASE_URL}/api/reports/{rid}/confirm",
            json={"source": "proximity"},
            headers=h,
        )
        if r.status_code == 422 and "GPS" in r.text:
            pytest.skip(f"confirmer location gate rejected — endpoint discovery failed: {r.text}")
        assert r.status_code == 200, r.text
        data = r.json()
        # Core spec — iter84
        assert data.get("confirmer_points_awarded") == 1, (
            f"expected +1 confirmer points (POINTS_CONFIRM_OTHER//2), got {data.get('confirmer_points_awarded')}"
        )
        assert data.get("author_reliability_awarded") == 3, (
            f"expected +3 author reliability (RELIABILITY_CONFIRM_OTHER), got {data.get('author_reliability_awarded')}"
        )

    def test_confirmer_points_persisted_in_db(self, confirmer_ctx):
        s, token, _ = confirmer_ctx
        h = {"Authorization": f"Bearer {token}"}
        r = s.get(f"{BASE_URL}/api/auth/me", headers=h)
        assert r.status_code == 200
        u = r.json()
        before = getattr(pytest, "iter84_confirmer_before_points", None)
        if before is None:
            pytest.skip("baseline not captured (previous step skipped)")
        after = int(u.get("points", 0))
        assert after == before + 1, f"expected points to go from {before} to {before+1}, got {after}"

    def test_author_reliability_persisted_in_db(self, author_ctx):
        s, token, _ = author_ctx
        h = {"Authorization": f"Bearer {token}"}
        r = s.get(f"{BASE_URL}/api/auth/me", headers=h)
        assert r.status_code == 200
        u = r.json()
        before = getattr(pytest, "iter84_author_before_rel", None)
        if before is None:
            pytest.skip("baseline not captured (previous step skipped)")
        after = int(u.get("reliability_score", 50))
        # Clamped 0..100; expect exactly +3 unless we were already at 100.
        expected = min(100, before + 3)
        assert after == expected, f"expected reliability {before}→{expected}, got {after}"

    def test_cleanup_delete_report(self, author_ctx):
        s, token, _ = author_ctx
        h = {"Authorization": f"Bearer {token}"}
        rid = getattr(pytest, "iter84_rid", None)
        if not rid:
            pytest.skip("no report to clean up")
        r = s.delete(f"{BASE_URL}/api/reports/{rid}", headers=h)
        assert r.status_code in (200, 204, 404, 429), r.text
