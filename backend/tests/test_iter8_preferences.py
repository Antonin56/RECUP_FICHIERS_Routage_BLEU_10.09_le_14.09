# Iter-8: PUT /api/profile/preferences + muted_types + optional heading/speed
import os
import uuid
import pytest
import requests


@pytest.fixture(scope="module")
def fresh_user(base_url):
    """Register a brand-new user so default preferences are observable."""
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    email = f"TEST_iter8_{uuid.uuid4().hex[:8]}@signmar.app"
    r = s.post(f"{base_url}/api/auth/register",
               json={"email": email, "password": "password123", "name": "iter8"})
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    data = r.json()
    return {"token": data["token"], "user": data["user"], "email": email}


class TestPreferencesDefaults:
    def test_new_user_defaults(self, base_url, fresh_user):
        h = {"Authorization": f"Bearer {fresh_user['token']}"}
        r = requests.get(f"{base_url}/api/auth/me", headers=h)
        assert r.status_code == 200
        body = r.json()
        # default notify_radius_km bumped to 15.0; muted_types defaults to []
        assert body.get("notify_radius_km") == 15.0
        assert body.get("muted_types") == []


class TestPreferencesUpdate:
    def test_update_radius_persists(self, base_url, fresh_user):
        h = {"Authorization": f"Bearer {fresh_user['token']}",
             "Content-Type": "application/json"}
        r = requests.put(f"{base_url}/api/profile/preferences",
                         json={"notify_radius_km": 20}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json().get("notify_radius_km") == 20.0
        # Verify via GET /auth/me
        r2 = requests.get(f"{base_url}/api/auth/me", headers=h)
        assert r2.status_code == 200
        assert r2.json().get("notify_radius_km") == 20.0

    def test_radius_out_of_range_low(self, base_url, fresh_user):
        h = {"Authorization": f"Bearer {fresh_user['token']}",
             "Content-Type": "application/json"}
        r = requests.put(f"{base_url}/api/profile/preferences",
                         json={"notify_radius_km": 0.1}, headers=h)
        assert r.status_code == 422

    def test_radius_out_of_range_high(self, base_url, fresh_user):
        h = {"Authorization": f"Bearer {fresh_user['token']}",
             "Content-Type": "application/json"}
        r = requests.put(f"{base_url}/api/profile/preferences",
                         json={"notify_radius_km": 750}, headers=h)
        assert r.status_code == 422

    def test_muted_types_persist_and_filter_unknown(self, base_url, fresh_user):
        h = {"Authorization": f"Bearer {fresh_user['token']}",
             "Content-Type": "application/json"}
        r = requests.put(
            f"{base_url}/api/profile/preferences",
            json={"muted_types": ["ofni", "pollution", "bogus_type", "fake"]},
            headers=h,
        )
        assert r.status_code == 200, r.text
        muted = r.json().get("muted_types") or []
        assert set(muted) == {"ofni", "pollution"}
        # Verify via GET /auth/me
        r2 = requests.get(f"{base_url}/api/auth/me", headers=h)
        assert r2.status_code == 200
        assert set(r2.json().get("muted_types") or []) == {"ofni", "pollution"}

    def test_requires_auth(self, base_url):
        r = requests.put(f"{base_url}/api/profile/preferences",
                         json={"notify_radius_km": 20})
        assert r.status_code == 401


# Iter-8 — heading/speed now optional in /reports for authorities + navigation
class TestReportsOptionalHeadingSpeed:
    def _post(self, base_url, token, payload):
        return requests.post(
            f"{base_url}/api/reports",
            json=payload,
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
        )

    def test_navigation_no_heading_no_speed(self, base_url, fresh_user):
        body = {
            "type": "autorites",
            "lat": 47.46,
            "lng": -2.92,
            "description": "TEST_iter8 nav no fields",
            "subtype": "affmar",
            "activity": "navigation",
        }
        r = self._post(base_url, fresh_user["token"], body)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["heading"] is None
        assert data["speed_knots"] is None
        assert data["activity"] == "navigation"

    def test_navigation_heading_only(self, base_url, fresh_user):
        body = {
            "type": "autorites",
            "lat": 47.46,
            "lng": -2.92,
            "description": "TEST_iter8 nav heading only",
            "subtype": "affmar",
            "activity": "navigation",
            "heading": 185,
        }
        r = self._post(base_url, fresh_user["token"], body)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["heading"] == 185
        assert data["speed_knots"] is None
