"""Iter-7 tests: POST /api/profile/location + proximity push side-effect on /api/reports."""
import os
import uuid
import pytest
import requests


def _h(token):
    return {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}


# --- /api/profile/location -------------------------------------------------
class TestProfileLocation:
    def test_location_requires_auth(self, base_url, api_client):
        r = api_client.post(f"{base_url}/api/profile/location", json={"lat": 47.5, "lng": -2.9})
        assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text}"

    def test_location_persists(self, base_url, auth_token, api_client):
        # POST /api/profile/location returns {ok: true}
        r = api_client.post(
            f"{base_url}/api/profile/location",
            headers=_h(auth_token),
            json={"lat": 47.461, "lng": -2.921},
        )
        assert r.status_code == 200, f"got {r.status_code}: {r.text}"
        body = r.json()
        assert body.get("ok") is True

        # Idempotent update with new coords
        r2 = api_client.post(
            f"{base_url}/api/profile/location",
            headers=_h(auth_token),
            json={"lat": 47.470, "lng": -2.930},
        )
        assert r2.status_code == 200
        assert r2.json().get("ok") is True

    def test_location_bad_payload_400(self, base_url, auth_token, api_client):
        r = api_client.post(
            f"{base_url}/api/profile/location",
            headers=_h(auth_token),
            json={"lat": "nope"},
        )
        # pydantic validation → 422
        assert r.status_code in (400, 422)


# --- Proximity push side-effect on POST /api/reports -----------------------
class TestProximityPushSideEffect:
    """The proximity push must NEVER cause /api/reports to fail, even when the
    Emergent push relay is a placeholder. We verify the request still succeeds
    when nearby users with recent GPS exist (so the recipients branch runs)."""

    @pytest.fixture(scope="class")
    def nearby_user_token(self, base_url):
        s = requests.Session()
        s.headers.update({"Content-Type": "application/json"})
        email = f"TEST_nearby_{uuid.uuid4().hex[:8]}@signmar.app"
        r = s.post(
            f"{base_url}/api/auth/register",
            json={"email": email, "password": "password123", "name": "Nearby"},
        )
        assert r.status_code == 200, r.text
        tok = r.json()["token"]
        # Push a recent GPS fix close to the upcoming report
        r2 = s.post(
            f"{base_url}/api/profile/location",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {tok}"},
            json={"lat": 47.460, "lng": -2.920},
        )
        assert r2.status_code == 200
        return tok

    def test_create_report_with_nearby_user_does_not_fail(
        self, base_url, auth_token, nearby_user_token, api_client
    ):
        # Author publishes a navigation authority report ~within 1km of nearby user
        payload = {
            "type": "autorites",
            "lat": 47.461,
            "lng": -2.921,
            "description": f"TEST_iter7_nav_{uuid.uuid4().hex[:6]}",
            "photos": [],
            "heading": 185,
            "speed_knots": 12,
            "subtype": "gendmar",
            "activity": "navigation",
        }
        r = api_client.post(f"{base_url}/api/reports", headers=_h(auth_token), json=payload)
        assert r.status_code == 200, f"create_report failed: {r.status_code} {r.text}"
        rep = r.json()
        assert rep["activity"] == "navigation"
        assert rep["heading"] == 185
        assert rep["speed_knots"] == 12

    def test_create_report_control_no_heading(self, base_url, auth_token, api_client):
        """An authorities/control report has no heading/speed and still succeeds."""
        payload = {
            "type": "autorites",
            "lat": 47.462,
            "lng": -2.923,
            "description": f"TEST_iter7_ctrl_{uuid.uuid4().hex[:6]}",
            "photos": [],
            "subtype": "police_env",
            "activity": "control",
        }
        r = api_client.post(f"{base_url}/api/reports", headers=_h(auth_token), json=payload)
        assert r.status_code == 200, r.text
        rep = r.json()
        assert rep["activity"] == "control"
        assert rep.get("heading") in (None,)
        assert rep.get("speed_knots") in (None,)
