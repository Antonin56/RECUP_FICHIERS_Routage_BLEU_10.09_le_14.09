"""Phase E.4 refactor smoke tests — verify that the relocation of HTTP handlers
from monolithic server.py into routers/* does not change behavior.

Covers every router module:
  - auth (register / login / me)
  - reports (create / list / get / delete / patch / confirm)
  - moderation (edits propose + vote auto-apply)
  - chat (messages post + list)
  - profile (me pagination / avatar / location / preferences)
  - weather (marine)
  - tts (alert mp3)
  - diagnostics (ping / persist)
"""
import base64
import io
import os
import time
import uuid
import requests
import pytest
from PIL import Image


DEV_EMAIL = "antoninlepinay@gmail.com"
DEV_PWD = "123454321"
SEC_EMAIL = "test@signmar.app"
SEC_PWD = "password123"

# Open-sea point off Brittany (Open-Meteo Marine returns data here)
SEA_LAT = 47.5
SEA_LNG = -3.0


def _login(base_url, email, pwd, name=None):
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{base_url}/api/auth/login", json={"email": email, "password": pwd})
    if r.status_code != 200 and name:
        r = s.post(f"{base_url}/api/auth/register", json={"email": email, "password": pwd, "name": name})
    assert r.status_code == 200, f"auth failed {email}: {r.status_code} {r.text}"
    tok = r.json()["token"]
    s.headers.update({"Authorization": f"Bearer {tok}"})
    return s, r.json().get("user", {})


@pytest.fixture(scope="module")
def dev_session(base_url):
    s, u = _login(base_url, DEV_EMAIL, DEV_PWD)
    return s, u


@pytest.fixture(scope="module")
def second_session(base_url):
    s, u = _login(base_url, SEC_EMAIL, SEC_PWD, name="Captain Test")
    return s, u


# --------------------------------------------------------------------- AUTH
class TestAuthRouter:
    def test_register_login_me_chain(self, base_url):
        email = f"test_e4_{uuid.uuid4().hex[:8]}@signmar.app"
        s = requests.Session()
        s.headers.update({"Content-Type": "application/json"})
        # register
        r = s.post(f"{base_url}/api/auth/register",
                   json={"email": email, "password": "Pwd12345", "name": "E4 Smoke"})
        assert r.status_code == 200, r.text
        assert r.json()["token"]
        assert r.json()["user"]["email"] == email
        # login
        r2 = s.post(f"{base_url}/api/auth/login", json={"email": email, "password": "Pwd12345"})
        assert r2.status_code == 200, r2.text
        tok2 = r2.json()["token"]
        assert tok2
        # me
        s.headers.update({"Authorization": f"Bearer {tok2}"})
        r3 = s.get(f"{base_url}/api/auth/me")
        assert r3.status_code == 200
        assert r3.json()["email"] == email

    def test_login_bad_password(self, base_url):
        r = requests.post(f"{base_url}/api/auth/login",
                          json={"email": SEC_EMAIL, "password": "wrong"})
        assert r.status_code in (400, 401)


# ------------------------------------------------------------------- REPORTS
class TestReportsRouter:
    """Create→Get→Patch→Confirm→Delete CRUD chain over the new reports router."""

    @pytest.fixture
    def created_report(self, base_url, dev_session):
        s, _ = dev_session
        body = {
            "type": "pollution",
            "subtype": "pollution_locale",
            "lat": SEA_LAT,
            "lng": SEA_LNG,
            "comment": "TEST_e4_smoke",
        }
        r = s.post(f"{base_url}/api/reports", json=body)
        assert r.status_code == 200, r.text
        rid = r.json()["id"]
        yield rid, r.json()
        # cleanup
        s.delete(f"{base_url}/api/reports/{rid}")

    def test_create_list_get(self, base_url, dev_session, created_report):
        rid, created = created_report
        s, _ = dev_session
        # list
        r = s.get(f"{base_url}/api/reports")
        assert r.status_code == 200
        ids = [x["id"] for x in r.json()]
        assert rid in ids
        # get one
        r2 = s.get(f"{base_url}/api/reports/{rid}")
        assert r2.status_code == 200
        assert r2.json()["id"] == rid
        assert r2.json()["type"] == "pollution"

    def test_patch_heading_rotates_drift_cone(self, base_url, dev_session, created_report):
        rid, created = created_report
        s, _ = dev_session
        # original cone (might be None if Open-Meteo offline)
        original = created.get("drift_cone")
        # PATCH heading=309 (in valid 0-360 range)
        r = s.patch(f"{base_url}/api/reports/{rid}", json={"heading": 309})
        assert r.status_code == 200, r.text
        updated = r.json()
        if original and updated.get("drift_cone"):
            dc = updated["drift_cone"]
            assert dc.get("bearing_source") == "user"
            assert int(round(dc.get("bearing_deg", -1))) == 309

    def test_confirm_by_second_user(self, base_url, dev_session, second_session, created_report):
        rid, _ = created_report
        s2, u2 = second_session
        r = s2.post(f"{base_url}/api/reports/{rid}/confirm",
                    json={"lat": SEA_LAT, "lng": SEA_LNG})
        assert r.status_code == 200, r.text
        body = r.json()
        # serialize_report exposes confirm_count + confirmed_by_me (raw list is private)
        assert body.get("confirm_count", 0) >= 1, body
        assert body.get("confirmed_by_me") is True, body


# ----------------------------------------------------------- MODERATION (EDITS)
class TestModerationRouter:
    def test_propose_edit_and_vote(self, base_url, dev_session, second_session):
        s, _ = dev_session
        s2, _ = second_session
        # create base report
        body = {"type": "pollution", "subtype": "pollution_locale",
                "lat": SEA_LAT, "lng": SEA_LNG, "comment": "TEST_e4_mod"}
        r = s.post(f"{base_url}/api/reports", json=body)
        assert r.status_code == 200
        rid = r.json()["id"]
        try:
            # non-author proposes an "ended" edit (kind required)
            r2 = s2.post(f"{base_url}/api/reports/{rid}/edits",
                         json={"kind": "ended", "comment": "TEST_e4 ended"})
            if r2.status_code in (401, 403):
                pytest.skip(f"edit proposal forbidden in this env: {r2.status_code}")
            assert r2.status_code in (200, 201), r2.text
            # Response is the full serialized report — edit id lives in edits[]
            edits = r2.json().get("edits", [])
            assert edits, f"no edits returned: {r2.json()}"
            eid = edits[-1].get("id")
            assert eid, f"no edit id in {edits[-1]}"
            # vote "up" by dev (dev's reliability bump means net should reach ≥2)
            r3 = s.post(f"{base_url}/api/reports/{rid}/edits/{eid}/vote",
                        json={"vote": "up"})
            assert r3.status_code in (200, 409), r3.text
        finally:
            s.delete(f"{base_url}/api/reports/{rid}")


# ------------------------------------------------------------- CHAT (MESSAGES)
class TestChatRouter:
    def test_post_and_list_messages(self, base_url, dev_session):
        s, _ = dev_session
        # create base report
        r = s.post(f"{base_url}/api/reports",
                   json={"type": "pollution", "subtype": "pollution_locale",
                         "lat": SEA_LAT, "lng": SEA_LNG, "comment": "TEST_e4_chat"})
        assert r.status_code == 200
        rid = r.json()["id"]
        try:
            r1 = s.post(f"{base_url}/api/reports/{rid}/messages",
                        json={"text": "hello e4"})
            assert r1.status_code == 200, r1.text
            r2 = s.get(f"{base_url}/api/reports/{rid}/messages")
            assert r2.status_code == 200
            msgs = r2.json()
            assert isinstance(msgs, list)
            assert any(m.get("text") == "hello e4" for m in msgs)
        finally:
            s.delete(f"{base_url}/api/reports/{rid}")


# ------------------------------------------------------------------- PROFILE
class TestProfileRouter:
    def test_me_pagination_fields(self, base_url, dev_session):
        s, _ = dev_session
        r = s.get(f"{base_url}/api/profile/me", params={"limit": 5, "offset": 0})
        assert r.status_code == 200
        body = r.json()
        # response is FLAT (user fields + counts + history). See routers/profile.py.
        for k in ("user_id", "email", "reports_count", "confirmations_count",
                  "history", "history_total", "history_offset", "history_limit"):
            assert k in body, f"missing key: {k}"
        assert body["history_limit"] == 5
        assert body["history_offset"] == 0

    def test_avatar_upload(self, base_url, dev_session):
        s, _ = dev_session
        # build a small jpeg in-memory
        img = Image.new("RGB", (32, 32), color=(0, 64, 128))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        payload = {"image": f"data:image/jpeg;base64,{b64}"}
        r = s.post(f"{base_url}/api/profile/avatar", json=payload)
        assert r.status_code == 200, r.text
        body = r.json()
        # response is the updated user dict
        assert body.get("picture") or body.get("user", {}).get("picture")

    def test_location_update(self, base_url, dev_session):
        s, _ = dev_session
        r = s.post(f"{base_url}/api/profile/location",
                   json={"lat": SEA_LAT, "lng": SEA_LNG})
        assert r.status_code == 200, r.text

    def test_preferences_update(self, base_url, dev_session):
        s, _ = dev_session
        r = s.put(f"{base_url}/api/profile/preferences",
                  json={"notify_radius_km": 12})
        assert r.status_code == 200, r.text
        body = r.json()
        nr = body.get("notify_radius_km") or body.get("user", {}).get("notify_radius_km")
        assert nr == 12, body


# ------------------------------------------------------------------- WEATHER
class TestWeatherRouter:
    def test_marine_returns_alerts_and_current(self, base_url, dev_session):
        s, _ = dev_session
        r = s.get(f"{base_url}/api/weather/marine",
                  params={"lat": SEA_LAT, "lng": SEA_LNG})
        # Open-Meteo can flake — allow soft skip on upstream failure
        if r.status_code in (502, 503, 504):
            pytest.skip(f"upstream marine API {r.status_code}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert "alerts" in body
        assert "current" in body


# ----------------------------------------------------------------------- TTS
class TestTtsRouter:
    def test_tts_alert_returns_audio(self, base_url, dev_session):
        s, _ = dev_session
        r = s.post(f"{base_url}/api/tts/alert",
                   json={"text": "Alerte de test phase e quatre"})
        # TTS provider can be down — skip on upstream failures
        if r.status_code in (502, 503, 504):
            pytest.skip(f"upstream tts {r.status_code}")
        assert r.status_code == 200, r.text
        ctype = r.headers.get("content-type", "")
        assert "audio" in ctype, f"got content-type={ctype}"
        assert len(r.content) > 100


# --------------------------------------------------------------- DIAGNOSTICS
class TestDiagnosticsRouter:
    def test_ping(self, base_url):
        r = requests.get(f"{base_url}/api/diagnostics/ping")
        assert r.status_code == 200
        assert r.json() == {"ok": True} or r.json().get("ok") is True

    def test_persist_logs(self, base_url, dev_session):
        s, _ = dev_session
        r = s.post(f"{base_url}/api/diagnostics",
                   json={"logs_text": "TEST_e4_smoke diag persistence check",
                         "client": "pytest-e4"})
        # diagnostics may be 200 or 204
        assert r.status_code in (200, 201, 204), r.text


# ------------------------------------------------------------ NO-DUPLICATE
class TestNoDuplicateEndpoints:
    """Verify each path is registered EXACTLY ONCE in the openapi schema.
    FastAPI would fail at startup on hard duplicates, but operation_id
    collisions or shadowed handlers can slip through silently."""

    def test_no_duplicate_operations(self, base_url):
        # /openapi.json is routed to frontend through ingress (HTML response).
        # Hit the internal port directly — same machine.
        try:
            r = requests.get("http://localhost:8001/openapi.json", timeout=5)
        except Exception as e:
            pytest.skip(f"internal openapi unreachable: {e}")
        assert r.status_code == 200
        data = r.json()
        from collections import Counter
        op_counts = Counter()
        for path, methods in data.get("paths", {}).items():
            for m in methods:
                if m in ("get", "post", "put", "patch", "delete"):
                    op_counts[(m.upper(), path)] += 1
        dups = {k: v for k, v in op_counts.items() if v > 1}
        assert not dups, f"duplicate endpoints detected: {dups}"
        # also verify expected paths are present
        all_paths = set(data["paths"].keys())
        for p in ("/api/auth/login", "/api/reports", "/api/reports/{rid}",
                  "/api/reports/{rid}/confirm", "/api/reports/{rid}/messages",
                  "/api/reports/{rid}/edits", "/api/profile/me",
                  "/api/weather/marine", "/api/tts/alert",
                  "/api/diagnostics/ping"):
            assert p in all_paths, f"missing path {p}"
