"""Iteration 46 — Fusion des rayons "Zone de veille" (10/07/2026).

Backend regression suite covering the review request:
 - OTP login (phone 0760071445 + mocked code 123456)
 - GET /api/reports returns demo seed
 - PUT /api/profile/preferences with notify_radius_km and muted_types
 - GET /api/auth/me reflects the updates
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_BACKEND_URL") or "https://nav-engine-i.preview.emergentagent.com"
BASE_URL = BASE_URL.rstrip("/")

PHONE = "0760071445"
OTP_CODE = "123456"
BYPASS = "qa-bypass-7f3d9a2e4c8b1f60"


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({
        "Content-Type": "application/json",
        "X-RateLimit-Bypass": BYPASS,
    })
    return s


@pytest.fixture(scope="module")
def token(api):
    # Request OTP
    r1 = api.post(f"{BASE_URL}/api/auth/otp/request", json={"phone": PHONE})
    assert r1.status_code in (200, 201), f"otp/request {r1.status_code}: {r1.text[:300]}"
    # Verify OTP → JWT
    r2 = api.post(f"{BASE_URL}/api/auth/otp/verify", json={"phone": PHONE, "code": OTP_CODE})
    assert r2.status_code == 200, f"otp/verify {r2.status_code}: {r2.text[:300]}"
    data = r2.json()
    assert "token" in data and "user" in data
    return data["token"]


# ── OTP / Auth ────────────────────────────────────────────────────────────
class TestOtpAuth:
    def test_otp_flow(self, token):
        assert isinstance(token, str) and len(token) > 20

    def test_auth_me(self, api, token):
        r = api.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text[:300]
        u = r.json()
        assert u.get("phone") in ("+33760071445", "0760071445") or u.get("email")


# ── Reports demo seed ─────────────────────────────────────────────────────
class TestReports:
    def test_list_reports(self, api):
        r = api.get(f"{BASE_URL}/api/reports")
        assert r.status_code == 200, r.text[:300]
        lst = r.json()
        assert isinstance(lst, list)
        # Demo seed ≈ 30 reports per problem statement
        assert len(lst) >= 20, f"Only {len(lst)} reports returned (expected ~30 demo)"


# ── Preferences (Zone de veille sync) ────────────────────────────────────
class TestPreferences:
    def test_update_notify_radius(self, api, token):
        h = {"Authorization": f"Bearer {token}"}
        r = api.put(
            f"{BASE_URL}/api/profile/preferences",
            headers=h,
            json={"notify_radius_km": 12},
        )
        assert r.status_code == 200, r.text[:300]
        # Verify persisted via /me
        me = api.get(f"{BASE_URL}/api/auth/me", headers=h).json()
        assert me.get("notify_radius_km") == 12, f"notify_radius_km not persisted: {me}"

    def test_update_notify_radius_5(self, api, token):
        """Simulates manual input of "5" in ZoneVigie input field."""
        h = {"Authorization": f"Bearer {token}"}
        r = api.put(
            f"{BASE_URL}/api/profile/preferences",
            headers=h,
            json={"notify_radius_km": 5},
        )
        assert r.status_code == 200
        me = api.get(f"{BASE_URL}/api/auth/me", headers=h).json()
        assert me.get("notify_radius_km") == 5

    def test_toggle_muted_type_pollution(self, api, token):
        h = {"Authorization": f"Bearer {token}"}
        # Add 'pollution' to muted_types
        r = api.put(
            f"{BASE_URL}/api/profile/preferences",
            headers=h,
            json={"muted_types": ["pollution"]},
        )
        assert r.status_code == 200, r.text[:300]
        me = api.get(f"{BASE_URL}/api/auth/me", headers=h).json()
        assert "pollution" in (me.get("muted_types") or []), f"muted_types: {me.get('muted_types')}"

        # Toggle off
        r2 = api.put(
            f"{BASE_URL}/api/profile/preferences",
            headers=h,
            json={"muted_types": []},
        )
        assert r2.status_code == 200
        me2 = api.get(f"{BASE_URL}/api/auth/me", headers=h).json()
        assert "pollution" not in (me2.get("muted_types") or [])

    def test_reset_notify_radius_default(self, api, token):
        """Restore a reasonable default so subsequent test runs stay clean."""
        h = {"Authorization": f"Bearer {token}"}
        r = api.put(
            f"{BASE_URL}/api/profile/preferences",
            headers=h,
            json={"notify_radius_km": 4},
        )
        assert r.status_code == 200
