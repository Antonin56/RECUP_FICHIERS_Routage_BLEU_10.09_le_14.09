"""SignMar backend API tests — auth, reports, chat, profile, weather."""
import time
import pytest


# --------------- AUTH ---------------
class TestAuth:
    def test_register_or_login_test_user(self, base_url, api_client, test_credentials):
        # idempotent: try login first
        r = api_client.post(f"{base_url}/api/auth/login", json={
            "email": test_credentials["email"], "password": test_credentials["password"]
        })
        if r.status_code != 200:
            r = api_client.post(f"{base_url}/api/auth/register", json=test_credentials)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "token" in data
        assert data["user"]["email"] == test_credentials["email"]
        assert "rank" in data["user"]

    def test_login_wrong_password(self, base_url, api_client, test_credentials):
        r = api_client.post(f"{base_url}/api/auth/login", json={
            "email": test_credentials["email"], "password": "wrong-password"
        })
        assert r.status_code == 401

    def test_me_with_jwt(self, base_url, api_client, auth_token, test_credentials):
        r = api_client.get(f"{base_url}/api/auth/me",
                           headers={"Authorization": f"Bearer {auth_token}"})
        assert r.status_code == 200
        assert r.json()["email"] == test_credentials["email"]

    def test_me_without_token(self, base_url, api_client):
        r = api_client.get(f"{base_url}/api/auth/me")
        assert r.status_code == 401


# --------------- REPORTS CRUD + CONFIRM ---------------
class TestReports:
    @pytest.fixture(scope="class")
    def created_report(self, base_url, auth_token):
        import requests
        r = requests.post(
            f"{base_url}/api/reports",
            headers={"Authorization": f"Bearer {auth_token}",
                     "Content-Type": "application/json"},
            json={
                "type": "autorites",
                "lat": 43.29, "lng": 5.36,
                "description": "TEST_authorities sighting",
                "photos": [],
            },
        )
        assert r.status_code == 200, r.text
        return r.json()

    def test_create_report(self, created_report):
        assert created_report["type"] == "autorites"
        assert created_report["lat"] == 43.29
        assert created_report["confirm_count"] == 0
        assert created_report["confirmed_by_me"] is False
        assert "id" in created_report
        assert created_report["author"]["name"]

    def test_list_reports_includes_created(self, base_url, api_client, auth_token, created_report):
        r = api_client.get(
            f"{base_url}/api/reports",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert r.status_code == 200
        ids = [x["id"] for x in r.json()]
        assert created_report["id"] in ids

    def test_get_single_report(self, base_url, api_client, auth_token, created_report):
        r = api_client.get(
            f"{base_url}/api/reports/{created_report['id']}",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert r.status_code == 200
        assert r.json()["id"] == created_report["id"]

    def test_confirm_report_increments(self, base_url, api_client, auth_token, created_report):
        # V1.2: self-confirmation is rejected → confirm with a SECOND user
        # who has a fresh at-sea GPS fix (both server-side requirements).
        import uuid as _uuid
        reg = api_client.post(f"{base_url}/api/auth/register", json={
            "email": f"TEST_confirm_{_uuid.uuid4().hex[:8]}@signmar.app",
            "password": "password123", "name": "Confirm Tester",
        })
        assert reg.status_code == 200, reg.text
        other_token = reg.json()["token"]
        loc = api_client.post(
            f"{base_url}/api/profile/location",
            headers={"Authorization": f"Bearer {other_token}"},
            json={"lat": 47.5, "lng": -3.0},
        )
        assert loc.status_code == 200, loc.text
        r = api_client.post(
            f"{base_url}/api/reports/{created_report['id']}/confirm",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["confirm_count"] == 1
        assert data["confirmed_by_me"] is True

    def test_invalid_report_type_rejected(self, base_url, api_client, auth_token):
        r = api_client.post(
            f"{base_url}/api/reports",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"type": "ufo", "lat": 0, "lng": 0},
        )
        assert r.status_code in (400, 422)

    def test_create_report_requires_auth(self, base_url, api_client):
        r = api_client.post(f"{base_url}/api/reports",
                            json={"type": "autorites", "lat": 0, "lng": 0})
        assert r.status_code == 401


# --------------- MESSAGES (chat) ---------------
class TestMessages:
    def test_post_and_list_messages(self, base_url, api_client, auth_token):
        # create a fresh report
        r = api_client.post(
            f"{base_url}/api/reports",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"type": "obstacle_nav", "lat": 43.0, "lng": 5.0,
                  "description": "TEST_chat parent"},
        )
        assert r.status_code == 200
        rid = r.json()["id"]

        m1 = api_client.post(
            f"{base_url}/api/reports/{rid}/messages",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"text": "TEST_first message"},
        )
        assert m1.status_code == 200
        assert m1.json()["text"] == "TEST_first message"

        time.sleep(0.05)
        m2 = api_client.post(
            f"{base_url}/api/reports/{rid}/messages",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"text": "TEST_second message"},
        )
        assert m2.status_code == 200

        listing = api_client.get(f"{base_url}/api/reports/{rid}/messages")
        assert listing.status_code == 200
        texts = [m["text"] for m in listing.json()]
        assert texts == ["TEST_first message", "TEST_second message"]


# --------------- PROFILE ---------------
class TestProfile:
    def test_profile_me(self, base_url, api_client, auth_token):
        r = api_client.get(f"{base_url}/api/profile/me",
                           headers={"Authorization": f"Bearer {auth_token}"})
        assert r.status_code == 200
        data = r.json()
        assert "reports_count" in data
        assert "history" in data
        assert "rank" in data
        assert "points" in data
        assert isinstance(data["history"], list)


# --------------- WEATHER ---------------
class TestWeather:
    def test_marine_weather_no_auth(self, base_url, api_client):
        r = api_client.get(f"{base_url}/api/weather/marine?lat=43.29&lng=5.36")
        assert r.status_code == 200
        data = r.json()
        assert "alerts" in data
        assert "current" in data
        assert isinstance(data["alerts"], list)
        assert len(data["alerts"]) >= 1
